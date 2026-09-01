import discord
from discord import app_commands
from discord.ext import commands, tasks
import pymysql
import os
from flask import Flask
from threading import Thread
from datetime import datetime
import aiohttp
import re
import asyncio
import io 

# ==========================================
# CONFIGURATION DE BASE
# ==========================================
TOKEN = os.environ.get('DISCORD_TOKEN', 'TON_TOKEN_ICI')
ID_SERVEUR_DISCORD = 1392952674604814487

# DB Config
DB_HOST = os.environ.get('DB_HOST', 'mysql-spicy-anomaly.alwaysdata.net')
DB_USER = os.environ.get('DB_USER', 'spicy-anomaly_admin')
DB_PASS = os.environ.get('DB_PASS', 'p7$8FhKDQ@3xgxMb')
DB_NAME = os.environ.get('DB_NAME', 'spicy-anomaly_stats')

URL_API_STATUS = os.environ.get('URL_API_STATUS', 'https://spicy-anomaly.alwaysdata.net/api_public.php')
URL_PANEL_WEB = "https://spicy-anomaly.alwaysdata.net"

NOM_ROLE_REPERE = "VIP"
NOM_SEPARATEUR = "─── Niveaux ───"
NOM_ROLE_LIE = "Lié"

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# ==========================================
# GESTION DYNAMIQUE DE LA CONFIGURATION (En BDD)
# ==========================================
CONFIG_CACHE = {}

def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor
    )

def init_db():
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS discord_config (
                    config_key VARCHAR(50) PRIMARY KEY,
                    config_value VARCHAR(255)
                )
            """)
        conn.commit()
    except Exception as e:
        print(f"Erreur init DB Config: {e}")
    finally:
        if 'conn' in locals() and conn.open: conn.close()

def get_config(key, default=0):
    if key in CONFIG_CACHE:
        return CONFIG_CACHE[key]
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT config_value FROM discord_config WHERE config_key = %s", (key,))
            res = cursor.fetchone()
        val = int(res['config_value']) if res else default
        CONFIG_CACHE[key] = val
        return val
    except:
        return default
    finally:
        if 'conn' in locals() and conn.open: conn.close()

def set_config(key, value):
    CONFIG_CACHE[key] = int(value)
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO discord_config (config_key, config_value) 
                VALUES (%s, %s) ON DUPLICATE KEY UPDATE config_value = %s
            """, (key, str(value), str(value)))
        conn.commit()
    except Exception as e:
        print(f"Erreur save config: {e}")
    finally:
        if 'conn' in locals() and conn.open: conn.close()

# ==========================================
# FONCTIONS UTILITAIRES
# ==========================================

async def get_or_create_role(guild, role_name, color=discord.Color.default()):
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        try:
            role = await guild.create_role(name=role_name, color=color, reason="Création auto")
            role_repere = discord.utils.get(guild.roles, name=NOM_ROLE_REPERE)
            if role_repere and guild.me.top_role.position > role_repere.position:
                await role.edit(position=max(1, role_repere.position - 1))
        except: pass
    return role

def get_ticket_overwrites(guild, user, type_ticket="support"):
    """
    Définit les permissions du ticket selon qu'il soit support ou recrutement.
    """
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
    }
    
    role_spicy = guild.get_role(get_config('ID_ROLE_SPICY_TEAM'))
    role_manager = guild.get_role(get_config('ID_ROLE_MANAGER'))
    
    # Les Managers voient toujours tout
    if role_manager: 
        overwrites[role_manager] = discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        
    # Le reste du Staff (Spicy Team) ne voit que les tickets support classiques, PAS les recrutements
    if role_spicy and type_ticket == "support": 
        overwrites[role_spicy] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
    return overwrites

async def process_ticket_closure(channel, closed_by, reason):
    messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
    transcript_text = f"--- Transcript du salon {channel.name} ---\nDate: {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\nFermé par: {closed_by.display_name}\nRaison: {reason}\n\n"
    for msg in messages:
        transcript_text += f"[{msg.created_at.strftime('%Y-%m-%d %H:%M')}] {msg.author.display_name}: {msg.clean_content}\n"

    ticket_owner = None
    for target, overwrite in channel.overwrites.items():
        if isinstance(target, discord.Member) and not target.bot:
            if not overwrite.manage_channels:
                ticket_owner = target
                break

    if ticket_owner:
        try:
            embed_dm = discord.Embed(title=f"🔒 Ton ticket `{channel.name}` a été fermé", description=f"**Raison :** {reason}\n**Fermé par :** {closed_by.mention}", color=0xe74c3c)
            file_dm = discord.File(io.BytesIO(transcript_text.encode('utf-8')), filename=f"transcript-{channel.name}.txt")
            await ticket_owner.send(embed=embed_dm, file=file_dm)
        except discord.Forbidden: pass

    salon_logs = get_config('ID_SALON_TRANSCRIPTS')
    if salon_logs:
        log_channel = channel.guild.get_channel(salon_logs)
        if log_channel:
            embed_log = discord.Embed(title=f"📄 Transcript : {channel.name}", description=f"**Fermé par :** {closed_by.mention}\n**Raison :** {reason}", color=0x2c3e50)
            if ticket_owner: embed_log.add_field(name="Propriétaire", value=ticket_owner.mention)
            file_log = discord.File(io.BytesIO(transcript_text.encode('utf-8')), filename=f"{channel.name}.txt")
            await log_channel.send(embed=embed_log, file=file_log)

    await asyncio.sleep(2)
    await channel.delete()


# ==========================================
# VUES PERSISTANTES ET MODAUX
# ==========================================

class ModalCloseTicket(discord.ui.Modal, title="Fermeture du ticket"):
    raison = discord.ui.TextInput(label="Raison de la fermeture", style=discord.TextStyle.paragraph, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("🔒 **Fermeture en cours et sauvegarde du transcript...**")
        await process_ticket_closure(interaction.channel, interaction.user, self.raison.value)

class TicketCloseView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket", emoji="🔒")
    async def btn_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Vérifie si l'user a le droit de fermer (Manage Channels OU Rôle Spicy OU Rôle Manager)
        has_perm = interaction.user.guild_permissions.manage_channels
        if get_config('ID_ROLE_SPICY_TEAM') and discord.utils.get(interaction.user.roles, id=get_config('ID_ROLE_SPICY_TEAM')): has_perm = True
        if get_config('ID_ROLE_MANAGER') and discord.utils.get(interaction.user.roles, id=get_config('ID_ROLE_MANAGER')): has_perm = True
        
        if has_perm:
            await interaction.response.send_modal(ModalCloseTicket())
        else: 
            await interaction.response.send_message("❌ Réservé au staff.", ephemeral=True)

class FAQCloseView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="✅ Ceci a résolu mon problème", style=discord.ButtonStyle.success, custom_id="faq_close_ticket")
    async def btn_faq_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔒 **Super ! Fermeture du ticket en cours...**")
        await process_ticket_closure(interaction.channel, interaction.user, "Résolu par la FAQ automatique.")

class ModalRecrutement(discord.ui.Modal):
    def __init__(self, role_nom: str, prefixe: str):
        super().__init__(title=f"Candidature {role_nom}")
        self.role_nom = role_nom
        self.prefixe = prefixe
        self.motivations = discord.ui.TextInput(label="Motivations", style=discord.TextStyle.paragraph, required=True, min_length=20)
        self.add_item(self.motivations)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        cat_id = get_config('ID_CATEGORIE_TICKETS')
        categorie = guild.get_channel(cat_id) if cat_id else None

        pseudo_clean = re.sub(r'[^a-z0-9]', '', interaction.user.display_name.lower()) or str(interaction.user.id)[:6]
        nom_salon = f"candid-{self.prefixe}-{pseudo_clean}"

        if discord.utils.get(guild.text_channels, name=nom_salon):
            return await interaction.followup.send(f"❌ Tu as déjà une candidature en cours.", ephemeral=True)

        try:
            # ICI ON PRECISE BIEN LE TYPE "recrutement" POUR CACHER LE TICKET A LA SPICY TEAM
            ticket = await guild.create_text_channel(name=nom_salon, category=categorie, overwrites=get_ticket_overwrites(guild, interaction.user, "recrutement"))
            await interaction.followup.send(f"✅ Ticket créé : {ticket.mention}", ephemeral=True)
            
            embed = discord.Embed(title=f"🎫 Candidature : {self.role_nom}", description=f"Bienvenue {interaction.user.mention} !\n\n**Motivations :**\n```\n{self.motivations.value}\n```", color=0x3498db)
            
            # Le ping fantôme pour la Spicy Team (si configuré)
            role_staff_id = get_config('ID_ROLE_SPICY_TEAM')
            mention_staff = f"<@&{role_staff_id}>" if role_staff_id else ""
            
            await ticket.send(content=f"{interaction.user.mention} | {mention_staff}", embed=embed, view=TicketCloseView())
        except Exception as e:
            await interaction.followup.send("❌ Erreur de création du ticket.", ephemeral=True)

class RecrutementPersistentView(discord.ui.View):
    """Cette vue tourne en permanence pour capter les clics sur l'embed de recrutement."""
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="Devenir Modérateur", style=discord.ButtonStyle.primary, custom_id="ticket_mod", emoji="🛡️")
    async def btn_mod(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalRecrutement("Modérateur", "mod"))
    @discord.ui.button(label="Devenir Animateur", style=discord.ButtonStyle.success, custom_id="ticket_anim", emoji="🎉")
    async def btn_anim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalRecrutement("Animateur", "anim"))

class ModalSupport(discord.ui.Modal, title="Ouvrir un ticket support"):
    sujet = discord.ui.TextInput(label="Sujet de ton ticket", style=discord.TextStyle.short, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        cat_id = get_config('ID_CATEGORIE_SUPPORT')
        categorie = guild.get_channel(cat_id) if cat_id else None

        pseudo_clean = re.sub(r'[^a-z0-9]', '', interaction.user.display_name.lower()) or str(interaction.user.id)[:6]
        nom_salon = f"ticket-{pseudo_clean}"

        if discord.utils.get(guild.text_channels, name=nom_salon):
            return await interaction.followup.send(f"❌ Tu as déjà un ticket support ouvert.", ephemeral=True)

        try:
            # ICI LE TICKET EST DE TYPE "support" DONC LA SPICY TEAM Y A ACCÈS
            ticket = await guild.create_text_channel(name=nom_salon, category=categorie, overwrites=get_ticket_overwrites(guild, interaction.user, "support"))
            await interaction.followup.send(f"✅ Ticket créé : {ticket.mention}", ephemeral=True)
            
            embed = discord.Embed(title=f"🛠️ Ticket Support", description=f"Bonjour {interaction.user.mention},\n\nMerci d'avoir contacté le support. Décris ton problème, la FAQ intelligente pourrait te répondre automatiquement !\n\n**Sujet :** {self.sujet.value}", color=0xf1c40f)
            
            role_staff_id = get_config('ID_ROLE_SPICY_TEAM')
            mention_staff = f"<@&{role_staff_id}>" if role_staff_id else ""
            
            await ticket.send(content=f"{interaction.user.mention} {mention_staff}", embed=embed, view=TicketCloseView())
        except Exception as e:
            await interaction.followup.send("❌ Erreur de création.", ephemeral=True)

class GeneralTicketView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Ouvrir un ticket", style=discord.ButtonStyle.primary, custom_id="btn_open_general_ticket", emoji="📩")
    async def btn_open(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalSupport())

class TicketStaffView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Aller sur le Panel", style=discord.ButtonStyle.link, url=URL_PANEL_WEB, emoji="🌐"))

    @discord.ui.button(label="Prendre le ticket", style=discord.ButtonStyle.primary, custom_id="btn_claim_ticket_ig", emoji="🙋")
    async def btn_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages: return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT steamid, pseudo FROM player_stats WHERE discord_id = %s", (str(interaction.user.id),))
                staff = cursor.fetchone()
                if not staff: return await interaction.response.send_message("❌ Ton compte Discord n'est pas lié.", ephemeral=True)
                cursor.execute("SELECT id, status FROM server_events_tickets WHERE discord_message_id = %s", (str(interaction.message.id),))
                ticket = cursor.fetchone()
                if not ticket: return await interaction.response.send_message("❌ Ticket introuvable.", ephemeral=True)
                if ticket['status'] in ['Pris', 'resolu', 'Résolu']: return await interaction.response.send_message("⚠️ Ce ticket est déjà pris.", ephemeral=True)
                
                cursor.execute("UPDATE server_events_tickets SET status = 'Pris', claimed_by = %s, claimed_steamid = %s WHERE id = %s", (staff['pseudo'], staff['steamid'], ticket['id']))
                conn.commit()
                embed = interaction.message.embeds[0]
                embed.color = 0xf39c12
                embed.add_field(name="🔄 Statut", value=f"Pris en charge par **{staff['pseudo']}**", inline=False)
                button.disabled = True
                await interaction.message.edit(embed=embed, view=self)
                await interaction.response.send_message("✅ Tu as été assigné à ce ticket.", ephemeral=True)
        except Exception: pass
        finally:
            if 'conn' in locals() and conn.open: conn.close()

    @discord.ui.button(label="Clôturer", style=discord.ButtonStyle.success, custom_id="btn_resolve_ticket_ig", emoji="✅")
    async def btn_resolve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages: return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT steamid FROM player_stats WHERE discord_id = %s", (str(interaction.user.id),))
                staff = cursor.fetchone()
                if not staff: return await interaction.response.send_message("❌ Compte non lié.", ephemeral=True)
                cursor.execute("SELECT id, status, claimed_steamid FROM server_events_tickets WHERE discord_message_id = %s", (str(interaction.message.id),))
                ticket = cursor.fetchone()
                if not ticket: return await interaction.response.send_message("❌ Ticket introuvable.", ephemeral=True)
                cursor.execute("UPDATE server_events_tickets SET status = 'resolu' WHERE id = %s", (ticket['id'],))
                cursor.execute("UPDATE player_stats SET tickets_resolus = tickets_resolus + 1 WHERE steamid = %s", (staff['steamid'],))
                conn.commit()
                embed = interaction.message.embeds[0]
                embed.color = 0x2ecc71
                if len(embed.fields) > 0 and embed.fields[-1].name == "🔄 Statut": embed.set_field_at(len(embed.fields)-1, name="✅ Statut", value="**Résolu**", inline=False)
                else: embed.add_field(name="✅ Statut", value="**Résolu**", inline=False)
                for child in self.children:
                    if isinstance(child, discord.ui.Button) and child.style != discord.ButtonStyle.link: child.disabled = True
                await interaction.message.edit(embed=embed, view=self)
                await interaction.response.send_message("✅ Incident clos.", ephemeral=True)
        except Exception: pass
        finally:
            if 'conn' in locals() and conn.open: conn.close()

class LierCompteModal(discord.ui.Modal, title="Liaison de compte Steam"):
    steamid_input = discord.ui.TextInput(label="Ton SteamID64", placeholder="Ex: 76561198...", min_length=17, max_length=25, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        steamid = self.steamid_input.value.strip()
        if not steamid.endswith('@steam'): steamid += '@steam'
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                affected = cursor.execute("UPDATE player_stats SET discord_id = %s WHERE steamid = %s", (str(interaction.user.id), steamid))
                conn.commit()
                if affected > 0:
                    cursor.execute("SELECT pseudo FROM player_stats WHERE steamid = %s", (steamid,))
                    user_data = cursor.fetchone()
                    in_game_pseudo = user_data['pseudo'] if user_data else None
                    guild = interaction.guild
                    if guild:
                        member = guild.get_member(interaction.user.id)
                        if member:
                            role_lie = await get_or_create_role(guild, NOM_ROLE_LIE, discord.Color.green())
                            if role_lie: await member.add_roles(role_lie)
                            if in_game_pseudo:
                                try: await member.edit(nick=in_game_pseudo)
                                except discord.Forbidden: pass
                    await interaction.response.send_message(f"✅ Compte lié au SteamID `{steamid}`.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ SteamID introuvable dans la base de données.", ephemeral=True)
        except Exception: await interaction.response.send_message("❌ Erreur BDD.", ephemeral=True)
        finally:
            if 'conn' in locals() and conn.open: conn.close()

class LierCompteView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
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
        init_db() # Initialiser la base de données pour la configuration dynamique
        
        guild = discord.Object(id=ID_SERVEUR_DISCORD)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

        self.add_view(RecrutementPersistentView())
        self.add_view(TicketCloseView())
        self.add_view(FAQCloseView())
        self.add_view(LierCompteView())
        self.add_view(TicketStaffView())
        self.add_view(GeneralTicketView()) 
        print("🔄 Commandes Slash (/) et Vues synchronisées !")

bot = SpicyBot()

# ==========================================
# EVENEMENTS ET BOUCLES
# ==========================================

@bot.event
async def on_ready():
    print(f'✅ Bot connecté en tant que {bot.user} !')
    for task in [check_levels_and_roles, update_server_status, update_live_leaderboard, check_new_tickets, election_mvp_hebdomadaire, check_new_events]:
        if not task.is_running(): task.start()

# --- FAQ INTELLIGENTE ---
@bot.event
async def on_message(message):
    if message.author.bot: return

    cat_support_id = get_config('ID_CATEGORIE_SUPPORT')
    if cat_support_id and message.channel.category_id == cat_support_id and "ticket-" in message.channel.name:
        content = message.content.lower()
        if "lier" in content and ("compte" in content or "discord" in content or "steam" in content or "comment" in content):
            embed = discord.Embed(title="🤖 FAQ Auto : Lier son compte", description="Pour lier ton compte, va dans le salon prévu à cet effet et clique sur le bouton **Lier mon compte Steam**. Tu devras y entrer ton SteamID64 (qui ressemble à `76561198...`).", color=0x3498db)
            await message.channel.send(content=f"{message.author.mention}, cette réponse automatique t'a-t-elle aidé ?", embed=embed, view=FAQCloseView())

        elif "boutique" in content or "vip" in content or "acheter" in content:
            embed = discord.Embed(title="🤖 FAQ Auto : Boutique & VIP", description=f"Toutes les informations sur les grades et la boutique sont disponibles sur notre site web : **{URL_PANEL_WEB}**", color=0x3498db)
            await message.channel.send(content=f"{message.author.mention}, cette réponse automatique t'a-t-elle aidé ?", embed=embed, view=FAQCloseView())

    await bot.process_commands(message)

@bot.event
async def on_member_join(member):
    if member.bot: return
    role_sep = await get_or_create_role(member.guild, NOM_SEPARATEUR, discord.Color.dark_grey())
    if role_sep and role_sep not in member.roles:
        try: await member.add_roles(role_sep)
        except: pass
    try:
        embed = discord.Embed(title="👋 Bienvenue sur Spicy Anomaly !", description="Pour suivre tes statistiques, apparaître dans le classement et débloquer des rôles exclusifs, lie ton compte Steam à ton compte Discord ci-dessous.", color=0xe63946)
        await member.send(embed=embed, view=LierCompteView())
    except: pass

@tasks.loop(minutes=1)
async def update_server_status():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(URL_API_STATUS, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    status = data.get('status', 'offline')
                    players = data.get('players', 0)
                    max_p = data.get('max', 20)
                    players_list = data.get('players_list', [])

                    if status == 'online': await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{players}/{max_p} joueurs sur SCP:SL"))
                    else: await bot.change_presence(activity=discord.Game(name="🔴 Serveur Hors Ligne"))

                    salon_id = get_config('ID_SALON_STATUT')
                    if salon_id:
                        guild = bot.get_guild(ID_SERVEUR_DISCORD)
                        if guild:
                            channel = guild.get_channel(salon_id)
                            if channel:
                                embed = discord.Embed(title="📊 Statut du Serveur SCP:SL", description=f"**État :** {'🟢 En ligne' if status == 'online' else '🔴 Hors ligne'}\n**Joueurs :** {players}/{max_p}", color=0x2ecc71 if status == 'online' else 0xe74c3c, timestamp=discord.utils.utcnow())
                                if players_list and status == 'online':
                                    noms = ", ".join(players_list)
                                    embed.add_field(name="En jeu actuellement", value=f"```\n{noms[:1018]}...\n```" if len(noms) > 1024 else f"```\n{noms}\n```", inline=False)
                                embed.set_footer(text="Actualisé en temps réel")
                                last_msg = None
                                async for msg in channel.history(limit=5):
                                    if msg.author == bot.user:
                                        last_msg = msg
                                        break
                                if last_msg: await last_msg.edit(embed=embed)
                                else: await channel.send(embed=embed)
    except Exception:
        await bot.change_presence(activity=discord.Game(name="🔴 Serveur Hors Ligne"))

@tasks.loop(hours=168)
async def election_mvp_hebdomadaire():
    guild = bot.get_guild(ID_SERVEUR_DISCORD)
    if not guild: return
    
    salon_id = get_config('ID_SALON_ANNONCES')
    salon_annonces = guild.get_channel(salon_id) if salon_id else None
    
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT steamid, discord_id, pseudo, xp, level FROM player_stats WHERE discord_id IS NOT NULL ORDER BY xp DESC LIMIT 1")
            mvp = cursor.fetchone()
            if not mvp: return
            cursor.execute("UPDATE player_stats SET custom_badge = '🏆' WHERE steamid = %s", (mvp['steamid'],))
            cursor.execute("UPDATE player_stats SET custom_badge = NULL WHERE steamid != %s AND custom_badge = '🏆'", (mvp['steamid'],))
            conn.commit()

        role_mvp = await get_or_create_role(guild, "🌟 MVP de la Semaine", discord.Color.gold())
        for member in guild.members:
            if role_mvp in member.roles and member.id != int(mvp['discord_id']): await member.remove_roles(role_mvp)

        nouveau_mvp_member = guild.get_member(int(mvp['discord_id']))
        if nouveau_mvp_member:
            await nouveau_mvp_member.add_roles(role_mvp)
            if salon_annonces:
                embed = discord.Embed(title="🌟 MVP DE LA SEMAINE", description=f"Félicitations à **{mvp['pseudo']}** qui remporte le titre de MVP cette semaine !", color=discord.Color.gold())
                await salon_annonces.send(content=f"🎉 {nouveau_mvp_member.mention}", embed=embed)
    except Exception: pass
    finally:
        if 'conn' in locals() and conn.open: conn.close()

@tasks.loop(seconds=15)
async def check_new_tickets():
    salon_id = get_config('ID_SALON_TICKETS_STAFF')
    if not salon_id: return
    guild = bot.get_guild(ID_SERVEUR_DISCORD)
    if not guild: return
    channel = guild.get_channel(salon_id)
    if not channel: return
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM server_events_tickets WHERE discord_message_id IS NULL AND (status = 'en attente' OR status = '')")
            new_tickets = cursor.fetchall()
            for ticket in new_tickets:
                embed = discord.Embed(title=f"🚨 Nouveau Signalement IG", description=f"**Signalé par:** `{ticket['reporter_pseudo']}`\n**Cible:** `{ticket['player_pseudo']}`", color=0xe74c3c)
                embed.add_field(name="Type", value=f"**{ticket['type_report']}**", inline=True)
                embed.add_field(name="Raison", value=f"_{ticket['reason']}_", inline=False)
                role_spicy_id = get_config('ID_ROLE_SPICY_TEAM')
                mention_staff = f"<@&{role_spicy_id}>" if role_spicy_id else ""
                msg = await channel.send(content=f"Nouveau ticket en jeu ! {mention_staff}", embed=embed, view=TicketStaffView())
                cursor.execute("UPDATE server_events_tickets SET discord_message_id = %s WHERE id = %s", (str(msg.id), ticket['id']))
                conn.commit()
    except Exception: pass
    finally:
        if 'conn' in locals() and conn.open: conn.close()

@tasks.loop(minutes=10)
async def update_live_leaderboard():
    salon_id = get_config('ID_SALON_CLASSEMENT')
    if not salon_id: return
    guild = bot.get_guild(ID_SERVEUR_DISCORD)
    if not guild: return
    channel = guild.get_channel(salon_id)
    if not channel: return
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT pseudo, xp, level, kills, escapes FROM player_stats ORDER BY level DESC, xp DESC LIMIT 10")
            top_xp = cursor.fetchall()
            cursor.execute("SELECT pseudo, kills, deaths, level FROM player_stats WHERE kills > 0 ORDER BY IF(deaths=0, kills, kills/deaths) DESC, kills DESC LIMIT 10")
            top_kills = cursor.fetchall()
        if not top_xp and not top_kills: return
        embed = discord.Embed(title="📊 CLASSEMENTS OFFICIELS SPICY ANOMALY", description=f"Mise à jour auto toutes les 10 min.\n🔗 **[Panel Web]({URL_PANEL_WEB})**", color=0xe63946, timestamp=discord.utils.utcnow())
        texte_xp = "".join([f"#{i+1} **{p['pseudo']}** • Niv. {p['level'] or 1} ({p['xp']:,} XP)\n" for i, p in enumerate(top_xp)])
        embed.add_field(name="🏆 Hall of Fame", value=texte_xp or "Aucune donnée.", inline=False)
        texte_kills = "".join([f"#{i+1} **{p['pseudo']}** • **{p['kills']}** Kills\n" for i, p in enumerate(top_kills)])
        embed.add_field(name="💀 Top 10 Tueurs", value=texte_kills or "Aucune donnée.", inline=False)
        async for msg in channel.history(limit=10):
            if msg.author == bot.user and msg.embeds and "CLASSEMENTS OFFICIELS" in msg.embeds[0].title:
                return await msg.edit(embed=embed)
        await channel.purge(limit=10)
        await channel.send(embed=embed)
    except Exception: pass
    finally:
        if 'conn' in locals() and conn.open: conn.close()

@tasks.loop(minutes=5)
async def check_levels_and_roles():
    guild = bot.get_guild(ID_SERVEUR_DISCORD)
    if not guild: return
    role_lie = await get_or_create_role(guild, NOM_ROLE_LIE, discord.Color.green())
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT discord_id, level, pseudo FROM player_stats WHERE discord_id IS NOT NULL")
            joueurs = cursor.fetchall()
            for j in joueurs:
                member = guild.get_member(int(j['discord_id']))
                if not member: continue
                if role_lie and role_lie not in member.roles: await member.add_roles(role_lie)
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
    except Exception: pass
    finally:
        if 'conn' in locals() and conn.open: conn.close()

@tasks.loop(minutes=1)
async def check_new_events(): pass

# ==========================================
# COMMANDES SLASH (/) DE CONFIGURATION DYNAMIQUE
# ==========================================

@bot.tree.command(name="config_salon", description="[ADMIN] Définir dynamiquement un salon/catégorie")
@app_commands.default_permissions(manage_guild=True)
@app_commands.choices(type_salon=[
    app_commands.Choice(name="Catégorie Support", value="ID_CATEGORIE_SUPPORT"),
    app_commands.Choice(name="Catégorie Candidatures", value="ID_CATEGORIE_TICKETS"),
    app_commands.Choice(name="Salon Annonces MVP", value="ID_SALON_ANNONCES"),
    app_commands.Choice(name="Salon Classement", value="ID_SALON_CLASSEMENT"),
    app_commands.Choice(name="Salon Alerte Reports IG", value="ID_SALON_TICKETS_STAFF"),
    app_commands.Choice(name="Salon Statut", value="ID_SALON_STATUT"),
    app_commands.Choice(name="Salon Logs Transcripts", value="ID_SALON_TRANSCRIPTS"),
])
async def config_salon(interaction: discord.Interaction, type_salon: app_commands.Choice[str], salon: discord.abc.GuildChannel):
    set_config(type_salon.value, salon.id)
    await interaction.response.send_message(f"✅ Configuration sauvegardée : **{type_salon.name}** est maintenant associé à {salon.mention}", ephemeral=True)

@bot.tree.command(name="config_role", description="[ADMIN] Définir dynamiquement un rôle staff")
@app_commands.default_permissions(manage_guild=True)
@app_commands.choices(type_role=[
    app_commands.Choice(name="Rôle Spicy Team (Staff Global)", value="ID_ROLE_SPICY_TEAM"),
    app_commands.Choice(name="Rôle Manager (Perms Max)", value="ID_ROLE_MANAGER"),
])
async def config_role(interaction: discord.Interaction, type_role: app_commands.Choice[str], role: discord.Role):
    set_config(type_role.value, role.id)
    await interaction.response.send_message(f"✅ Configuration sauvegardée : **{type_role.name}** est maintenant associé à {role.mention}", ephemeral=True)


# ==========================================
# COMMANDES SLASH (/) DE GESTION STAFF & TICKETS
# ==========================================

class TicketGroup(app_commands.Group): pass
ticket_cmd_group = TicketGroup(name="ticket", description="Gérer les tickets")
bot.tree.add_command(ticket_cmd_group)

@ticket_cmd_group.command(name="add", description="[STAFF] Ajouter un membre à ce ticket")
@app_commands.default_permissions(manage_messages=True)
async def ticket_add(interaction: discord.Interaction, membre: discord.Member):
    if "ticket" not in interaction.channel.name and "candid" not in interaction.channel.name:
        return await interaction.response.send_message("❌ Réservé aux tickets.", ephemeral=True)
    await interaction.channel.set_permissions(membre, read_messages=True, send_messages=True, attach_files=True)
    await interaction.response.send_message(f"✅ {membre.mention} a été ajouté au ticket.")

@ticket_cmd_group.command(name="remove", description="[STAFF] Retirer un membre de ce ticket")
@app_commands.default_permissions(manage_messages=True)
async def ticket_remove(interaction: discord.Interaction, membre: discord.Member):
    if "ticket" not in interaction.channel.name and "candid" not in interaction.channel.name:
        return await interaction.response.send_message("❌ Réservé aux tickets.", ephemeral=True)
    await interaction.channel.set_permissions(membre, overwrite=None)
    await interaction.response.send_message(f"✅ {membre.mention} a été retiré du ticket.")

@bot.tree.command(name="recrutement", description="[STAFF] Lancer une campagne de recrutement")
@app_commands.default_permissions(manage_guild=True)
async def recrutement_cmd(interaction: discord.Interaction, places_moderateur: int, places_animateur: int):
    if places_moderateur <= 0 and places_animateur <= 0:
        return await interaction.response.send_message("❌ Il faut au moins une place ouverte dans l'un des postes.", ephemeral=True)

    embed = discord.Embed(
        title="📢 CAMPAGNE DE RECRUTEMENT OUVERTE",
        description="L'équipe de Spicy Anomaly s'agrandit ! Nous recherchons de nouveaux membres motivés pour rejoindre le Staff.\n\n**Postes actuellement à pourvoir :**",
        color=0xe63946
    )
    if places_moderateur > 0:
        embed.add_field(name="🛡️ Modérateur", value=f"Places disponibles : **{places_moderateur}**", inline=False)
    if places_animateur > 0:
        embed.add_field(name="🎉 Animateur", value=f"Places disponibles : **{places_animateur}**", inline=False)
    
    embed.set_footer(text="Cliquez sur les boutons ci-dessous pour postuler (soyez détaillés !)")

    # Création d'une vue temporaire pour l'affichage (les boutons déclencheront la vue persistante)
    view = discord.ui.View(timeout=None)
    if places_moderateur > 0:
        view.add_item(discord.ui.Button(label="Devenir Modérateur", style=discord.ButtonStyle.primary, custom_id="ticket_mod", emoji="🛡️"))
    if places_animateur > 0:
        view.add_item(discord.ui.Button(label="Devenir Animateur", style=discord.ButtonStyle.success, custom_id="ticket_anim", emoji="🎉"))

    await interaction.channel.send(content="@everyone", embed=embed, view=view)
    await interaction.response.send_message("✅ Campagne de recrutement envoyée.", ephemeral=True)

@bot.tree.command(name="warn", description="[STAFF] Avertir un joueur (Enregistré en BDD)")
@app_commands.default_permissions(manage_messages=True)
async def warn_user(interaction: discord.Interaction, membre: discord.Member, raison: str):
    # Sécurité anti "Staff warn un Staff"
    role_spicy_id = get_config('ID_ROLE_SPICY_TEAM')
    if role_spicy_id:
        role_spicy = interaction.guild.get_role(role_spicy_id)
        if role_spicy in membre.roles:
            if not interaction.user.guild_permissions.manage_guild:
                return await interaction.response.send_message("❌ Action refusée. Tu ne peux pas avertir un membre de l'équipe, contacte la direction.", ephemeral=True)

    target_id = str(membre.id)
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT steamid FROM player_stats WHERE discord_id = %s", (target_id,))
            cible = cursor.fetchone()
            if cible:
                cursor.execute("INSERT INTO player_infractions (steamid, type_sanction, reason, staff_pseudo) VALUES (%s, %s, %s, %s)", (cible['steamid'], 'Warn', raison, interaction.user.display_name))
                cursor.execute("UPDATE player_stats SET warnings = warnings + 1 WHERE steamid = %s", (cible['steamid'],))
                conn.commit()
            
            embed = discord.Embed(title="⚠️ Nouvel Avertissement", color=0xe67e22)
            embed.add_field(name="Membre", value=membre.mention, inline=True)
            embed.add_field(name="Staff", value=interaction.user.mention, inline=True)
            embed.add_field(name="Raison", value=raison, inline=False)
            if not cible: embed.set_footer(text="Attention: Le joueur n'est pas lié à un compte Steam. Le warn n'apparaîtra pas sur le site web.")
            
            await interaction.response.send_message(embed=embed)

            try:
                dm_embed = discord.Embed(title="⚠️ Tu as reçu un avertissement", description=f"**Raison :** {raison}\n\nMerci de respecter le règlement de Spicy Anomaly.", color=0xe74c3c)
                await membre.send(embed=dm_embed)
            except discord.Forbidden:
                await interaction.followup.send("*(Le joueur a ses messages privés désactivés, il n'a pas été notifié par message privé)*", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur BDD : {e}", ephemeral=True)
    finally:
        if 'conn' in locals() and conn.open: conn.close()


# ==========================================
# COMMANDES SLASH (/) : JOUEURS
# ==========================================

@bot.tree.command(name="delier", description="Retirer la liaison entre ton compte Discord et Steam")
async def delier_cmd(interaction: discord.Interaction):
    discord_id = str(interaction.user.id)
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            affected = cursor.execute("UPDATE player_stats SET discord_id = NULL WHERE discord_id = %s", (discord_id,))
            if affected > 0:
                conn.commit()
                role_lie = discord.utils.get(interaction.guild.roles, name=NOM_ROLE_LIE)
                if role_lie and role_lie in interaction.user.roles:
                    try: await interaction.user.remove_roles(role_lie)
                    except: pass
                await interaction.response.send_message("✅ Ton compte a bien été délié avec succès.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Ton compte n'était pas lié.", ephemeral=True)
    except Exception:
        await interaction.response.send_message("❌ Erreur base de données.", ephemeral=True)
    finally:
        if 'conn' in locals() and conn.open: conn.close()

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
                await interaction.response.send_message("❌ Ton compte n'est pas lié.", ephemeral=True)
    finally:
        if 'conn' in locals() and conn.open: conn.close()

@bot.tree.command(name="profil", description="Affiche ton profil complet")
async def voir_profil(interaction: discord.Interaction):
    discord_id = str(interaction.user.id)
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM player_stats WHERE discord_id = %s", (discord_id,))
            joueur = cursor.fetchone()
            if joueur:
                k, d = joueur['kills'] or 0, joueur['deaths'] or 0
                kd = f"{(k/d):.2f}" if d > 0 else str(k)
                embed = discord.Embed(title=f"👤 Profil de {joueur['pseudo']}", color=0x3498db)
                embed.add_field(name="⭐ Niveau", value=f"{joueur['level']}", inline=True)
                embed.add_field(name="✨ XP", value=f"{joueur['xp']:,}", inline=True)
                embed.add_field(name="📈 K/D Ratio", value=f"{kd}", inline=True)
                embed.add_field(name="💀 Kills", value=f"{k}", inline=True)
                embed.add_field(name="🚪 Escapes", value=f"{joueur.get('escapes', 0)}", inline=True)
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("❌ Ton compte n'est pas lié.", ephemeral=True)
    finally:
        if 'conn' in locals() and conn.open: conn.close()

@bot.tree.command(name="casier", description="Affiche le contenu de ton casier (Inventaire IG)")
async def voir_casier(interaction: discord.Interaction):
    discord_id = str(interaction.user.id)
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT steamid FROM player_stats WHERE discord_id = %s", (discord_id,))
            joueur = cursor.fetchone()
            if not joueur:
                return await interaction.response.send_message("❌ Ton compte n'est pas lié.", ephemeral=True)

            embed = discord.Embed(title="🎒 Ton Casier", description="Voici les objets stockés sur ton compte :", color=0x95a5a6)
            embed.add_field(name="En développement", value="L'affichage des items est en cours de liaison avec la base de données web.", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
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