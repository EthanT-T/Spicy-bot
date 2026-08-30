import discord
from discord import app_commands
from discord.ext import commands, tasks
import pymysql
import os
from flask import Flask
from threading import Thread
from datetime import datetime, timedelta
import pytz
import aiohttp
import re
import asyncio

# ==========================================
# CONFIGURATION (Via Variables d'Environnement)
# ==========================================

TOKEN = os.environ.get('DISCORD_TOKEN')

try:
    ID_SERVEUR_DISCORD = int(os.environ.get('ID_SERVEUR_DISCORD', 1392952674604814487))
except (TypeError, ValueError):
    ID_SERVEUR_DISCORD = 1392952674604814487

try:
    ID_SALON_ANNONCES = int(os.environ.get('ID_SALON_ANNONCES', 0))
except (TypeError, ValueError):
    ID_SALON_ANNONCES = 0

try:
    ID_CATEGORIE_TICKETS = int(os.environ.get('ID_CATEGORIE_TICKETS', 0))
except (TypeError, ValueError):
    ID_CATEGORIE_TICKETS = 0

try:
    ID_SALON_CLASSEMENT = int(os.environ.get('ID_SALON_CLASSEMENT', 0))
except (TypeError, ValueError):
    ID_SALON_CLASSEMENT = 0

try:
    ID_SALON_TICKETS_STAFF = int(os.environ.get('ID_SALON_TICKETS_STAFF', 0)) 
except (TypeError, ValueError):
    ID_SALON_TICKETS_STAFF = 0

NOM_ROLE_REPERE = "VIP"
NOM_SEPARATEUR = "─── Niveaux ───"
NOM_ROLE_LIE = "Lié"

DB_HOST = os.environ.get('DB_HOST', 'mysql-spicy-anomaly.alwaysdata.net')
DB_USER = os.environ.get('DB_USER', 'spicy-anomaly_admin')
DB_PASS = os.environ.get('DB_PASS', 'p7$8FhKDQ@3xgxMb')
DB_NAME = os.environ.get('DB_NAME', 'spicy-anomaly_stats')

URL_API_STATUS = os.environ.get('URL_API_STATUS', 'https://spicy-anomaly.alwaysdata.net/api_public.php')
URL_PANEL_WEB = "https://spicy-anomaly.alwaysdata.net"

intents = discord.Intents.default()
intents.members = True

# ==========================================
# FONCTIONS UTILITAIRES
# ==========================================

def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor
    )

def is_valid_url(url):
    regex = re.compile(
        r'^(?:http|ftp)s?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?(?:/[-A-Z0-9+&@#/%=~_|!:,.;]*)?$', re.IGNORECASE)
    return re.match(regex, url) is not None

async def get_or_create_role(guild, role_name, color=discord.Color.default()):
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        try:
            role = await guild.create_role(name=role_name, color=color, reason="Création auto système de bot")
            print(f"✨ Nouveau rôle créé : {role_name}")
            role_repere = discord.utils.get(guild.roles, name=NOM_ROLE_REPERE)
            if role_repere and guild.me.top_role.position > role_repere.position:
                new_position = max(1, role_repere.position - 1)
                await role.edit(position=new_position)
        except Exception as e:
            print(f"Erreur création rôle {role_name}: {e}")
    return role

# ==========================================
# VUES PERSISTANTES ET MODAUX
# ==========================================

class TicketStaffView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Aller sur le Panel", style=discord.ButtonStyle.link, url=URL_PANEL_WEB, emoji="🌐"))

    @discord.ui.button(label="Prendre le ticket", style=discord.ButtonStyle.primary, custom_id="btn_claim_ticket_ig", emoji="🙋")
    async def btn_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Accès refusé. Réservé au staff.", ephemeral=True)

        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT steamid, pseudo FROM player_stats WHERE discord_id = %s", (str(interaction.user.id),))
                staff = cursor.fetchone()
                
                if not staff:
                    return await interaction.response.send_message("❌ Ton compte Discord n'est pas lié. Impossible de t'assigner le ticket en base de données.", ephemeral=True)

                cursor.execute("SELECT id, status FROM server_events_tickets WHERE discord_message_id = %s", (str(interaction.message.id),))
                ticket = cursor.fetchone()

                if not ticket:
                    return await interaction.response.send_message("❌ Ticket introuvable.", ephemeral=True)

                if ticket['status'] in ['Pris', 'resolu', 'Résolu']:
                    return await interaction.response.send_message("⚠️ Ce ticket est déjà en cours de traitement ou résolu.", ephemeral=True)

                cursor.execute("UPDATE server_events_tickets SET status = 'Pris', claimed_by = %s, claimed_steamid = %s WHERE id = %s", (staff['pseudo'], staff['steamid'], ticket['id']))
                conn.commit()

                embed = interaction.message.embeds[0]
                embed.color = 0xf39c12 # Orange (En cours)
                embed.add_field(name="🔄 Statut", value=f"Pris en charge par **{staff['pseudo']}**", inline=False)
                
                button.disabled = True
                await interaction.message.edit(embed=embed, view=self)
                await interaction.response.send_message("✅ Tu as été assigné à ce ticket.", ephemeral=True)
                
        except Exception as e:
            print(f"Erreur prise de ticket: {e}")
            await interaction.response.send_message("❌ Une erreur technique est survenue.", ephemeral=True)
        finally:
            if 'conn' in locals() and conn.open:
                conn.close()

    @discord.ui.button(label="Clôturer", style=discord.ButtonStyle.success, custom_id="btn_resolve_ticket_ig", emoji="✅")
    async def btn_resolve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)

        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT steamid FROM player_stats WHERE discord_id = %s", (str(interaction.user.id),))
                staff = cursor.fetchone()
                
                if not staff:
                    return await interaction.response.send_message("❌ Ton compte n'est pas lié.", ephemeral=True)

                cursor.execute("SELECT id, status, claimed_steamid FROM server_events_tickets WHERE discord_message_id = %s", (str(interaction.message.id),))
                ticket = cursor.fetchone()

                if not ticket:
                    return await interaction.response.send_message("❌ Ticket introuvable.", ephemeral=True)

                if ticket['status'] in ['resolu', 'Résolu']:
                    return await interaction.response.send_message("⚠️ Ce ticket est déjà clos.", ephemeral=True)

                if ticket['status'] == 'Pris' and ticket['claimed_steamid'] != staff['steamid'] and not interaction.user.guild_permissions.administrator:
                    return await interaction.response.send_message("❌ Tu ne peux pas clôturer un ticket pris par un autre membre du staff.", ephemeral=True)

                cursor.execute("UPDATE server_events_tickets SET status = 'resolu' WHERE id = %s", (ticket['id'],))
                cursor.execute("UPDATE player_stats SET tickets_resolus = tickets_resolus + 1 WHERE steamid = %s", (staff['steamid'],))
                conn.commit()

                embed = interaction.message.embeds[0]
                embed.color = 0x2ecc71 # Vert (Terminé)
                if len(embed.fields) > 0 and embed.fields[-1].name == "🔄 Statut":
                    embed.set_field_at(len(embed.fields)-1, name="✅ Statut", value="**Résolu**", inline=False)
                else:
                    embed.add_field(name="✅ Statut", value="**Résolu**", inline=False)
                
                for child in self.children:
                    if isinstance(child, discord.ui.Button) and child.style != discord.ButtonStyle.link:
                        child.disabled = True
                
                await interaction.message.edit(embed=embed, view=self)
                await interaction.response.send_message("✅ Incident clos et archivé dans tes statistiques.", ephemeral=True)
                
        except Exception as e:
            print(f"Erreur résolution ticket: {e}")
            await interaction.response.send_message("❌ Une erreur technique est survenue.", ephemeral=True)
        finally:
            if 'conn' in locals() and conn.open:
                conn.close()


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket", emoji="🔒")
    async def btn_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("🔒 **Fermeture du ticket dans 5 secondes...**")
            await asyncio.sleep(5)
            await interaction.channel.delete()
        else:
            await interaction.response.send_message("❌ Seul un membre du staff peut fermer ce ticket.", ephemeral=True)

class RecrutementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Postuler Modérateur", style=discord.ButtonStyle.primary, custom_id="ticket_mod", emoji="🛡️")
    async def btn_mod(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.creer_ticket(interaction, "Modérateur", "mod")

    @discord.ui.button(label="Postuler Animateur", style=discord.ButtonStyle.success, custom_id="ticket_anim", emoji="🎉")
    async def btn_anim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.creer_ticket(interaction, "Animateur", "anim")

    async def creer_ticket(self, interaction: discord.Interaction, role_nom: str, prefixe: str):
        guild = interaction.guild
        categorie = guild.get_channel(ID_CATEGORIE_TICKETS) if ID_CATEGORIE_TICKETS else None

        pseudo_ig = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT pseudo FROM player_stats WHERE discord_id = %s", (str(interaction.user.id),))
                res = cursor.fetchone()
                if res and res['pseudo']:
                    pseudo_ig = res['pseudo']
        except:
            pass
        finally:
            if 'conn' in locals() and conn.open:
                conn.close()

        raw_name = pseudo_ig if pseudo_ig else interaction.user.display_name
        pseudo_clean = re.sub(r'[^a-z0-9]', '', raw_name.lower())
        if not pseudo_clean:
            pseudo_clean = str(interaction.user.id)[:6]
            
        nom_salon = f"ticket-{prefixe}-{pseudo_clean}"
        
        existant = discord.utils.get(guild.text_channels, name=nom_salon)
        if existant:
            await interaction.response.send_message(f"❌ Tu as déjà un ticket d'ouvert : {existant.mention}", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }

        try:
            ticket = await guild.create_text_channel(name=nom_salon, category=categorie, overwrites=overwrites, reason=f"Ticket recrutement {role_nom}")
            await interaction.response.send_message(f"✅ Ton ticket a été créé : {ticket.mention}", ephemeral=True)
            
            nom_affichage = pseudo_ig if pseudo_ig else interaction.user.mention
            
            embed = discord.Embed(
                title=f"🎫 Candidature {role_nom}",
                description=f"Bienvenue **{nom_affichage}** !\n\nL'équipe administrative traitera ta demande sous peu. En attendant, merci de préparer ta candidature ou de lister tes motivations ci-dessous.",
                color=0x2ecc71 if prefixe == "anim" else 0x3498db
            )
            
            await ticket.send(f"{interaction.user.mention} | Candidature", embed=embed, view=TicketCloseView())
        except Exception as e:
            await interaction.response.send_message("❌ Erreur lors de la création du ticket. Contacte un administrateur.", ephemeral=True)
            print(f"Erreur Ticket: {e}")

class LierCompteModal(discord.ui.Modal, title="Liaison de compte Steam"):
    steamid_input = discord.ui.TextInput(
        label="Ton SteamID64",
        placeholder="Ex: 76561198...",
        min_length=17,
        max_length=25,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        steamid = self.steamid_input.value.strip()
        if not steamid.endswith('@steam'):
            steamid += '@steam'
            
        discord_id = str(interaction.user.id)
        
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                sql = "UPDATE player_stats SET discord_id = %s WHERE steamid = %s"
                affected = cursor.execute(sql, (discord_id, steamid))
                conn.commit()
                
                if affected > 0:
                    cursor.execute("SELECT pseudo FROM player_stats WHERE steamid = %s", (steamid,))
                    user_data = cursor.fetchone()
                    in_game_pseudo = user_data['pseudo'] if user_data else None

                    guild = interaction.client.get_guild(ID_SERVEUR_DISCORD)
                    if guild:
                        member = guild.get_member(interaction.user.id)
                        if member:
                            role_lie = await get_or_create_role(guild, NOM_ROLE_LIE, discord.Color.green())
                            if role_lie:
                                await member.add_roles(role_lie)
                            
                            if in_game_pseudo:
                                try:
                                    await member.edit(nick=in_game_pseudo)
                                except discord.Forbidden:
                                    pass

                    msg = f"✅ Félicitations ! Compte lié avec succès au SteamID `{steamid}`."
                    if in_game_pseudo:
                        msg += f" Ton pseudo Discord a été mis à jour en **{in_game_pseudo}**."
                        
                    await interaction.response.send_message(msg, ephemeral=True)
                else:
                    await interaction.response.send_message("❌ SteamID introuvable dans la base de données.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message("❌ Une erreur technique est survenue.", ephemeral=True)
        finally:
            if 'conn' in locals() and conn.open:
                conn.close()

class LierCompteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔗 Lier mon compte Steam", style=discord.ButtonStyle.success, custom_id="btn_lier_compte")
    async def btn_lier(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LierCompteModal())

# ==========================================
# CLASSE BOT PRINCIPALE
# ==========================================

class SpicyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        guild = discord.Object(id=ID_SERVEUR_DISCORD)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        
        self.add_view(RecrutementView())
        self.add_view(TicketCloseView())
        self.add_view(LierCompteView())
        self.add_view(TicketStaffView())
        
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("ALTER TABLE server_events_tickets ADD COLUMN discord_message_id VARCHAR(50) DEFAULT NULL")
            conn.commit()
        except:
            pass 
        finally:
            if 'conn' in locals() and conn.open:
                conn.close()

        print("🔄 Commandes Slash (/) et Vues synchronisées avec succès !")

bot = SpicyBot()

# ==========================================
# EVENEMENTS ET BOUCLES
# ==========================================

@bot.event
async def on_ready():
    print(f'✅ Bot connecté en tant que {bot.user} !')
    if not check_levels_and_roles.is_running():
        check_levels_and_roles.start()
    if not check_new_events.is_running():
        check_new_events.start()
    if not update_server_status.is_running():
        update_server_status.start()
    if not update_live_leaderboard.is_running():
        update_live_leaderboard.start()
    if not check_new_tickets.is_running():
        check_new_tickets.start()
    if not election_mvp_hebdomadaire.is_running():
        election_mvp_hebdomadaire.start()

@bot.event
async def on_member_join(member):
    if member.bot: return
    
    role_sep = await get_or_create_role(member.guild, NOM_SEPARATEUR, discord.Color.dark_grey())
    if role_sep and role_sep not in member.roles:
        try:
            await member.add_roles(role_sep)
        except discord.Forbidden:
            pass

    try:
        embed = discord.Embed(
            title="👋 Bienvenue sur Spicy Anomaly !", 
            description="Pour suivre tes statistiques (Kills, XP, Niveau), apparaître dans le classement et débloquer des rôles exclusifs, tu dois lier ton compte Steam à ton compte Discord.\n\nClique sur le bouton ci-dessous pour le faire ! 👇", 
            color=0xe63946
        )
        await member.send(embed=embed, view=LierCompteView())
    except discord.Forbidden:
        pass


@tasks.loop(hours=168)
async def election_mvp_hebdomadaire():
    guild = bot.get_guild(ID_SERVEUR_DISCORD)
    if not guild: return
    salon_annonces = guild.get_channel(ID_SALON_ANNONCES)
    
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT steamid, discord_id, pseudo, xp, level FROM player_stats WHERE discord_id IS NOT NULL ORDER BY xp DESC LIMIT 1")
            mvp = cursor.fetchone()
            if not mvp: return

            steamid_mvp = mvp['steamid']
            discord_id_mvp = int(mvp['discord_id'])
            pseudo_mvp = mvp['pseudo']
            
            cursor.execute("UPDATE player_stats SET custom_badge = '🏆' WHERE steamid = %s", (steamid_mvp,))
            cursor.execute("UPDATE player_stats SET custom_badge = NULL WHERE steamid != %s AND custom_badge = '🏆'", (steamid_mvp,))
            conn.commit()

        role_mvp_nom = "🌟 MVP de la Semaine"
        role_mvp = await get_or_create_role(guild, role_mvp_nom, discord.Color.gold())
        
        for member in guild.members:
            if role_mvp in member.roles and member.id != discord_id_mvp:
                await member.remove_roles(role_mvp)
                
        nouveau_mvp_member = guild.get_member(discord_id_mvp)
        if nouveau_mvp_member:
            await nouveau_mvp_member.add_roles(role_mvp)
            if salon_annonces:
                embed = discord.Embed(
                    title="🌟 MVP DE LA SEMAINE",
                    description=f"Félicitations à **{pseudo_mvp}** qui remporte le titre de MVP cette semaine !\n\n🎁 **Récompenses :**\n• Rôle exclusif **{role_mvp_nom}**\n• Badge trophée `🏆` sur son profil web",
                    color=discord.Color.gold()
                )
                await salon_annonces.send(content=f"🎉 {nouveau_mvp_member.mention}", embed=embed)
    except Exception as e:
        print(f"Erreur MVP: {e}")
    finally:
        if 'conn' in locals() and conn.open: conn.close()


@tasks.loop(seconds=15)
async def check_new_tickets():
    if not ID_SALON_TICKETS_STAFF: return
    guild = bot.get_guild(ID_SERVEUR_DISCORD)
    if not guild: return
    channel = guild.get_channel(ID_SALON_TICKETS_STAFF)
    if not channel: return

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM server_events_tickets WHERE discord_message_id IS NULL AND (status = 'en attente' OR status = '')")
            new_tickets = cursor.fetchall()

            for ticket in new_tickets:
                embed = discord.Embed(
                    title=f"🚨 Nouveau Signalement IG",
                    description=f"**Signalé par:** `{ticket['reporter_pseudo']}`\n**Cible:** `{ticket['player_pseudo']}`",
                    color=0xe74c3c
                )
                embed.add_field(name="Type", value=f"**{ticket['type_report']}**", inline=True)
                embed.add_field(name="Raison", value=f"_{ticket['reason']}_", inline=False)
                embed.set_footer(text=f"Reçu le {ticket['date_report'].strftime('%d/%m/%Y à %H:%M') if isinstance(ticket['date_report'], datetime) else ticket['date_report']}")

                msg = await channel.send(embed=embed, view=TicketStaffView())
                cursor.execute("UPDATE server_events_tickets SET discord_message_id = %s WHERE id = %s", (str(msg.id), ticket['id']))
                conn.commit()
    except Exception as e:
        print(f"Erreur Check Tickets IG: {e}")
    finally:
        if 'conn' in locals() and conn.open: conn.close()


@tasks.loop(minutes=1)
async def update_server_status():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(URL_API_STATUS, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('status') == 'online':
                        players = data.get('players', 0)
                        max_p = data.get('max', 20)
                        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{players}/{max_p} joueurs sur SCP:SL"))
                    else:
                        await bot.change_presence(activity=discord.Game(name="🔴 Serveur Hors Ligne"))
                else:
                    await bot.change_presence(activity=discord.Game(name="🔴 Serveur Hors Ligne"))
    except Exception:
        await bot.change_presence(activity=discord.Game(name="🔴 Serveur Hors Ligne"))


@tasks.loop(minutes=10)
async def update_live_leaderboard():
    if not ID_SALON_CLASSEMENT: return
    guild = bot.get_guild(ID_SERVEUR_DISCORD)
    if not guild: return
    channel = guild.get_channel(ID_SALON_CLASSEMENT)
    if not channel: return

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT pseudo, xp, level, kills, escapes FROM player_stats ORDER BY level DESC, xp DESC LIMIT 10")
            top_xp = cursor.fetchall()
            cursor.execute("SELECT pseudo, kills, deaths, level FROM player_stats WHERE kills > 0 ORDER BY IF(deaths=0, kills, kills/deaths) DESC, kills DESC LIMIT 10")
            top_kills = cursor.fetchall()

        if not top_xp and not top_kills: return

        embed = discord.Embed(
            title="📊 CLASSEMENTS OFFICIELS SPICIY ANOMALY",
            description=f"Mise à jour automatique toutes les **10 minutes**.\n🔗 **[Panel Web]({URL_PANEL_WEB})**",
            color=0xe63946,
            timestamp=discord.utils.utcnow()
        )

        def get_rank_str(i):
            return "🥇" if i==0 else ("🥈" if i==1 else ("🥉" if i==2 else f"`#{i+1}`"))

        texte_xp = "".join([f"{get_rank_str(i)} **{p['pseudo']}** • Niv. {p['level'] or 1} ({p['xp']:,} XP)\n" for i, p in enumerate(top_xp)])
        embed.add_field(name="🏆 Hall of Fame", value=texte_xp or "Aucune donnée.", inline=False)

        texte_kills = "".join([f"{get_rank_str(i)} **{p['pseudo']}** • **{p['kills']}** Kills\n" for i, p in enumerate(top_kills)])
        embed.add_field(name="💀 Top 10 Tueurs", value=texte_kills or "Aucune donnée.", inline=False)

        async for msg in channel.history(limit=10):
            if msg.author == bot.user and msg.embeds and "CLASSEMENTS OFFICIELS" in msg.embeds[0].title:
                await msg.edit(embed=embed)
                return
        await channel.purge(limit=10)
        await channel.send(embed=embed)
    except Exception as e:
        print(f"Erreur Leaderboard: {e}")
    finally:
        if 'conn' in locals() and conn.open: conn.close()


@tasks.loop(minutes=1)
async def check_new_events():
    guild = bot.get_guild(ID_SERVEUR_DISCORD)
    if not guild: return
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM server_events WHERE discord_event_id IS NULL OR discord_event_id = ''")
            new_events = cursor.fetchall()
            for ev in new_events:
                # Logique de création d'événements gérée par le bot
                pass
    except Exception as e:
        pass
    finally:
        if 'conn' in locals() and conn.open: conn.close()


@tasks.loop(minutes=5)
async def check_levels_and_roles():
    guild = bot.get_guild(ID_SERVEUR_DISCORD)
    if not guild: return
    role_sep = await get_or_create_role(guild, NOM_SEPARATEUR, discord.Color.dark_grey())
    role_lie = await get_or_create_role(guild, NOM_ROLE_LIE, discord.Color.green())
    
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT discord_id, level, pseudo FROM player_stats WHERE discord_id IS NOT NULL")
            joueurs = cursor.fetchall()
            for j in joueurs:
                member = guild.get_member(int(j['discord_id']))
                if not member: continue
                if role_lie and role_lie not in member.roles:
                    await member.add_roles(role_lie)
                if j['pseudo'] and member.display_name != j['pseudo'] and member.nick != j['pseudo']:
                    try: await member.edit(nick=j['pseudo'])
                    except: pass
                
                lvl = j['level']
                palier = 1 if lvl < 5 else (lvl // 5) * 5
                nom_role_cible = f"Niveau {palier}"
                role_cible = await get_or_create_role(guild, nom_role_cible, discord.Color.teal())
                
                roles_a_retirer = [r for r in member.roles if r.name.startswith("Niveau ") and r.name != nom_role_cible]
                if roles_a_retirer: await member.remove_roles(*roles_a_retirer)
                if role_cible and role_cible not in member.roles: await member.add_roles(role_cible)
    except Exception as e:
        print(f"Erreur rôles: {e}")
    finally:
        if 'conn' in locals() and conn.open: conn.close()

# ==========================================
# COMMANDES SLASH (/)
# ==========================================

@bot.tree.command(name="setup_liaison", description="[STAFF] Créer le bouton permanent de liaison")
@app_commands.default_permissions(manage_guild=True)
async def setup_liaison_cmd(interaction: discord.Interaction, salon: discord.TextChannel):
    embed = discord.Embed(title="🔗 Liaison de compte Steam", description="Associe ton compte Discord à ton SteamID pour suivre tes statistiques.", color=0xe63946)
    await salon.send(embed=embed, view=LierCompteView())
    await interaction.response.send_message(f"✅ Panneau généré dans {salon.mention}.", ephemeral=True)


@bot.tree.command(name="stats", description="Affiche tes statistiques")
async def voir_stats(interaction: discord.Interaction):
    discord_id = str(interaction.user.id)
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT pseudo, xp, level, kills, deaths, escapes FROM player_stats WHERE discord_id = %s", (discord_id,))
            joueur = cursor.fetchone()
            if joueur:
                k, d = joueur['kills'] or 0, joueur['deaths'] or 0
                kd = f"{(k/d):.2f}" if d > 0 else str(k)
                embed = discord.Embed(title=f"📊 Stats de {joueur['pseudo']}", url=URL_PANEL_WEB, color=0xe63946)
                embed.add_field(name="Niveau", value=f"⭐ {joueur['level']}", inline=True)
                embed.add_field(name="XP", value=f"✨ {joueur['xp']} XP", inline=True)
                embed.add_field(name="Ratio K/D", value=f"📈 {kd}", inline=True)
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("❌ Compte non lié.", ephemeral=True)
    finally:
        if 'conn' in locals() and conn.open: conn.close()

# ==========================================
# GESTION WEB (FLASK)
# ==========================================

app = Flask('')
@app.route('/')
def home(): return "Bot en ligne !"

def run_flask(): app.run(host='0.0.0.0', port=8080)
Thread(target=run_flask).start()

bot.run(TOKEN)