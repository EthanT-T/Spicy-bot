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

# IDs Serveur et Salons
try: ID_SERVEUR_DISCORD = int(os.environ.get('ID_SERVEUR_DISCORD', 1392952674604814487))
except: ID_SERVEUR_DISCORD = 1392952674604814487

try: ID_SALON_ANNONCES = int(os.environ.get('ID_SALON_ANNONCES', 0))
except: ID_SALON_ANNONCES = 0

try: ID_CATEGORIE_TICKETS = int(os.environ.get('ID_CATEGORIE_TICKETS', 0))
except: ID_CATEGORIE_TICKETS = 0

try: ID_SALON_CLASSEMENT = int(os.environ.get('ID_SALON_CLASSEMENT', 0))
except: ID_SALON_CLASSEMENT = 0

try: ID_SALON_TICKETS_STAFF = int(os.environ.get('ID_SALON_TICKETS_STAFF', 0)) 
except: ID_SALON_TICKETS_STAFF = 0

# IDs Rôles 
try: ID_ROLE_SPICY_TEAM = int(os.environ.get('ID_ROLE_SPICY_TEAM', 0))
except: ID_ROLE_SPICY_TEAM = 0

try: ID_ROLE_MANAGER = int(os.environ.get('ID_ROLE_MANAGER', 0))
except: ID_ROLE_MANAGER = 0

NOM_ROLE_REPERE = "VIP"
NOM_SEPARATEUR = "─── Niveaux ───"
NOM_ROLE_LIE = "Lié"

# DB Config
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

async def get_or_create_role(guild, role_name, color=discord.Color.default()):
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        try:
            role = await guild.create_role(name=role_name, color=color, reason="Création auto système de bot")
            role_repere = discord.utils.get(guild.roles, name=NOM_ROLE_REPERE)
            if role_repere and guild.me.top_role.position > role_repere.position:
                new_position = max(1, role_repere.position - 1)
                await role.edit(position=new_position)
        except Exception as e:
            print(f"Erreur création rôle {role_name}: {e}")
    return role

def get_ticket_overwrites(guild, user):
    """Génère les permissions de base pour un ticket (User + Staff)."""
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
    }
    
    # Ajout des rôles Staff / Managers
    role_spicy = guild.get_role(ID_ROLE_SPICY_TEAM)
    role_manager = guild.get_role(ID_ROLE_MANAGER)
    
    if role_spicy:
        overwrites[role_spicy] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    if role_manager:
        overwrites[role_manager] = discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        
    return overwrites

# ==========================================
# VUES PERSISTANTES ET MODAUX
# ==========================================

class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket", emoji="🔒")
    async def btn_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.guild_permissions.manage_channels or discord.utils.get(interaction.user.roles, id=ID_ROLE_SPICY_TEAM):
            await interaction.response.send_message("🔒 **Fermeture du ticket dans 5 secondes...**")
            await asyncio.sleep(5)
            await interaction.channel.delete()
        else:
            await interaction.response.send_message("❌ Seul un membre du staff peut fermer ce ticket.", ephemeral=True)


class ModalRecrutement(discord.ui.Modal):
    def __init__(self, role_nom: str, prefixe: str):
        super().__init__(title=f"Candidature {role_nom}")
        self.role_nom = role_nom
        self.prefixe = prefixe
        
        self.motivations = discord.ui.TextInput(
            label="Pourquoi veux-tu nous rejoindre ?",
            style=discord.TextStyle.paragraph,
            placeholder="Détaille tes motivations, tes disponibilités...",
            required=True,
            min_length=20
        )
        self.add_item(self.motivations)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        categorie = guild.get_channel(ID_CATEGORIE_TICKETS) if ID_CATEGORIE_TICKETS else None

        pseudo_ig = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT pseudo FROM player_stats WHERE discord_id = %s", (str(interaction.user.id),))
                res = cursor.fetchone()
                if res and res['pseudo']: pseudo_ig = res['pseudo']
        except: pass
        finally:
            if 'conn' in locals() and conn.open: conn.close()

        raw_name = pseudo_ig if pseudo_ig else interaction.user.display_name
        pseudo_clean = re.sub(r'[^a-z0-9]', '', raw_name.lower()) or str(interaction.user.id)[:6]
        nom_salon = f"candid-{self.prefixe}-{pseudo_clean}"

        if discord.utils.get(guild.text_channels, name=nom_salon):
            return await interaction.followup.send(f"❌ Tu as déjà un ticket de candidature ouvert : {discord.utils.get(guild.text_channels, name=nom_salon).mention}", ephemeral=True)

        overwrites = get_ticket_overwrites(guild, interaction.user)

        try:
            ticket = await guild.create_text_channel(name=nom_salon, category=categorie, overwrites=overwrites, reason=f"Candidature {self.role_nom}")
            await interaction.followup.send(f"✅ Ton ticket a été créé : {ticket.mention}", ephemeral=True)

            nom_affichage = pseudo_ig if pseudo_ig else interaction.user.mention
            
            embed = discord.Embed(
                title=f"🎫 Candidature : {self.role_nom}",
                description=f"Bienvenue **{nom_affichage}** !\nL'équipe traitera ta demande sous peu.\n\n**Motivations renseignées :**\n```\n{self.motivations.value}\n```",
                color=0x2ecc71 if self.prefixe == "anim" else 0x3498db
            )
            
            mention_staff = f"<@&{ID_ROLE_SPICY_TEAM}>" if ID_ROLE_SPICY_TEAM else "@here"
            await ticket.send(f"{interaction.user.mention} | {mention_staff}", embed=embed, view=TicketCloseView())
        except Exception as e:
            await interaction.followup.send("❌ Erreur lors de la création du ticket.", ephemeral=True)
            print(f"Erreur Ticket Recrutement: {e}")

class RecrutementView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Postuler Modérateur", style=discord.ButtonStyle.primary, custom_id="ticket_mod", emoji="🛡️")
    async def btn_mod(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalRecrutement("Modérateur", "mod"))

    @discord.ui.button(label="Postuler Animateur", style=discord.ButtonStyle.success, custom_id="ticket_anim", emoji="🎉")
    async def btn_anim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalRecrutement("Animateur", "anim"))


class ModalSupport(discord.ui.Modal, title="Ouvrir un ticket support"):
    sujet = discord.ui.TextInput(
        label="Sujet de ton ticket",
        style=discord.TextStyle.short,
        placeholder="Ex: Problème en jeu, question boutique...",
        required=True
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        categorie = guild.get_channel(ID_CATEGORIE_TICKETS) if ID_CATEGORIE_TICKETS else None
        
        pseudo_clean = re.sub(r'[^a-z0-9]', '', interaction.user.display_name.lower()) or str(interaction.user.id)[:6]
        nom_salon = f"ticket-{pseudo_clean}"

        # --- VÉRIFICATION LIMITE D'UN TICKET SUPPORT ---
        existant = discord.utils.get(guild.text_channels, name=nom_salon)
        if existant:
            return await interaction.followup.send(f"❌ Tu as déjà un ticket support ouvert : {existant.mention}", ephemeral=True)
        # -----------------------------------------------

        overwrites = get_ticket_overwrites(guild, interaction.user)

        try:
            ticket = await guild.create_text_channel(name=nom_salon, category=categorie, overwrites=overwrites)
            await interaction.followup.send(f"✅ Ton ticket a été créé : {ticket.mention}", ephemeral=True)

            embed = discord.Embed(
                title=f"🛠️ Ticket Support",
                description=f"Bonjour {interaction.user.mention},\n\nMerci d'avoir contacté le support. Un membre de la Spicy Team va te répondre.\n\n**Sujet :** {self.sujet.value}",
                color=0xf1c40f
            )
            
            mention_staff = f"<@&{ID_ROLE_SPICY_TEAM}>" if ID_ROLE_SPICY_TEAM else ""
            await ticket.send(f"{interaction.user.mention} {mention_staff}", embed=embed, view=TicketCloseView())
        except Exception as e:
            await interaction.followup.send("❌ Erreur lors de la création.", ephemeral=True)
            print(f"Erreur Ticket Support: {e}")

class GeneralTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ouvrir un ticket", style=discord.ButtonStyle.primary, custom_id="btn_open_general_ticket", emoji="📩")
    async def btn_open(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalSupport())


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
                if not staff: return await interaction.response.send_message("❌ Ton compte Discord n'est pas lié.", ephemeral=True)
                cursor.execute("SELECT id, status FROM server_events_tickets WHERE discord_message_id = %s", (str(interaction.message.id),))
                ticket = cursor.fetchone()
                if not ticket: return await interaction.response.send_message("❌ Ticket introuvable.", ephemeral=True)
                if ticket['status'] in ['Pris', 'resolu', 'Résolu']: return await interaction.response.send_message("⚠️ Ce ticket est déjà en cours de traitement.", ephemeral=True)
                cursor.execute("UPDATE server_events_tickets SET status = 'Pris', claimed_by = %s, claimed_steamid = %s WHERE id = %s", (staff['pseudo'], staff['steamid'], ticket['id']))
                conn.commit()
                embed = interaction.message.embeds[0]
                embed.color = 0xf39c12
                embed.add_field(name="🔄 Statut", value=f"Pris en charge par **{staff['pseudo']}**", inline=False)
                button.disabled = True
                await interaction.message.edit(embed=embed, view=self)
                await interaction.response.send_message("✅ Tu as été assigné à ce ticket.", ephemeral=True)
        except Exception as e: print(e)
        finally: 
            if 'conn' in locals() and conn.open: conn.close()

    @discord.ui.button(label="Clôturer", style=discord.ButtonStyle.success, custom_id="btn_resolve_ticket_ig", emoji="✅")
    async def btn_resolve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Accès refusé.", ephemeral=True)
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
                if len(embed.fields) > 0 and embed.fields[-1].name == "🔄 Statut":
                    embed.set_field_at(len(embed.fields)-1, name="✅ Statut", value="**Résolu**", inline=False)
                else: embed.add_field(name="✅ Statut", value="**Résolu**", inline=False)
                for child in self.children:
                    if isinstance(child, discord.ui.Button) and child.style != discord.ButtonStyle.link: child.disabled = True
                await interaction.message.edit(embed=embed, view=self)
                await interaction.response.send_message("✅ Incident clos.", ephemeral=True)
        except Exception as e: print(e)
        finally:
            if 'conn' in locals() and conn.open: conn.close()


class LierCompteModal(discord.ui.Modal, title="Liaison de compte Steam"):
    steamid_input = discord.ui.TextInput(label="Ton SteamID64", placeholder="Ex: 76561198...", min_length=17, max_length=25, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        steamid = self.steamid_input.value.strip()
        if not steamid.endswith('@steam'): steamid += '@steam'
        discord_id = str(interaction.user.id)
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                affected = cursor.execute("UPDATE player_stats SET discord_id = %s WHERE steamid = %s", (discord_id, steamid))
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
                            if role_lie: await member.add_roles(role_lie)
                            if in_game_pseudo:
                                try: await member.edit(nick=in_game_pseudo)
                                except discord.Forbidden: pass
                    msg = f"✅ Compte lié avec succès au SteamID `{steamid}`."
                    await interaction.response.send_message(msg, ephemeral=True)
                else:
                    await interaction.response.send_message("❌ SteamID introuvable.", ephemeral=True)
        except Exception as e: print(e)
        finally:
            if 'conn' in locals() and conn.open: conn.close()

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
        self.add_view(GeneralTicketView()) 

        print("🔄 Commandes Slash (/) et Vues synchronisées avec succès !")

bot = SpicyBot()

# ==========================================
# EVENEMENTS ET BOUCLES
# ==========================================
@bot.event
async def on_ready():
    print(f'✅ Bot connecté en tant que {bot.user} !')
    if not check_levels_and_roles.is_running(): check_levels_and_roles.start()
    if not check_new_events.is_running(): check_new_events.start()
    if not update_server_status.is_running(): update_server_status.start()
    if not update_live_leaderboard.is_running(): update_live_leaderboard.start()
    if not check_new_tickets.is_running(): check_new_tickets.start()
    if not election_mvp_hebdomadaire.is_running(): election_mvp_hebdomadaire.start()

@bot.event
async def on_member_join(member):
    if member.bot: return
    role_sep = await get_or_create_role(member.guild, NOM_SEPARATEUR, discord.Color.dark_grey())
    if role_sep and role_sep not in member.roles:
        try: await member.add_roles(role_sep)
        except discord.Forbidden: pass
    try:
        embed = discord.Embed(
            title="👋 Bienvenue sur Spicy Anomaly !", 
            description="Pour suivre tes statistiques (Kills, XP, Niveau), apparaître dans le classement et débloquer des rôles exclusifs, tu dois lier ton compte Steam à ton compte Discord.\n\nClique sur le bouton ci-dessous pour le faire ! 👇", 
            color=0xe63946
        )
        await member.send(embed=embed, view=LierCompteView())
    except: pass

@tasks.loop(hours=168)
async def election_mvp_hebdomadaire():
    pass 

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
                
                mention_staff = f"<@&{ID_ROLE_SPICY_TEAM}>" if ID_ROLE_SPICY_TEAM else ""
                
                msg = await channel.send(content=f"Nouveau ticket en jeu ! {mention_staff}", embed=embed, view=TicketStaffView())
                cursor.execute("UPDATE server_events_tickets SET discord_message_id = %s WHERE id = %s", (str(msg.id), ticket['id']))
                conn.commit()
    except Exception as e: print(f"Erreur Check Tickets IG: {e}")
    finally:
        if 'conn' in locals() and conn.open: conn.close()

@tasks.loop(minutes=1)
async def update_server_status(): pass 
@tasks.loop(minutes=10)
async def update_live_leaderboard(): pass 
@tasks.loop(minutes=1)
async def check_new_events(): pass 
@tasks.loop(minutes=5)
async def check_levels_and_roles(): pass 


# ==========================================
# COMMANDES SLASH (/) : TICKETS & ADMIN
# ==========================================

@bot.tree.command(name="ticket_setup", description="[STAFF] Créer un panel de tickets support classique")
@app_commands.default_permissions(manage_guild=True)
async def ticket_setup(interaction: discord.Interaction, salon: discord.TextChannel, titre: str = "Besoin d'aide ?", description: str = "Clique ci-dessous pour ouvrir un ticket de support."):
    embed = discord.Embed(title=titre, description=description, color=0x3498db)
    await salon.send(embed=embed, view=GeneralTicketView())
    await interaction.response.send_message(f"✅ Panel de tickets créé dans {salon.mention}.", ephemeral=True)

class TicketGroup(app_commands.Group):
    pass
ticket_cmd_group = TicketGroup(name="ticket", description="Gérer les tickets")
bot.tree.add_command(ticket_cmd_group)

@ticket_cmd_group.command(name="add", description="[STAFF] Ajouter un membre à ce ticket")
@app_commands.default_permissions(manage_messages=True)
async def ticket_add(interaction: discord.Interaction, membre: discord.Member):
    if "ticket" not in interaction.channel.name and "candid" not in interaction.channel.name:
        return await interaction.response.send_message("❌ Cette commande ne s'utilise que dans un ticket.", ephemeral=True)
    
    await interaction.channel.set_permissions(membre, read_messages=True, send_messages=True, attach_files=True)
    await interaction.response.send_message(f"✅ {membre.mention} a été ajouté au ticket.")

@ticket_cmd_group.command(name="remove", description="[STAFF] Retirer un membre de ce ticket")
@app_commands.default_permissions(manage_messages=True)
async def ticket_remove(interaction: discord.Interaction, membre: discord.Member):
    if "ticket" not in interaction.channel.name and "candid" not in interaction.channel.name:
        return await interaction.response.send_message("❌ Cette commande ne s'utilise que dans un ticket.", ephemeral=True)
    
    await interaction.channel.set_permissions(membre, overwrite=None)
    await interaction.response.send_message(f"✅ {membre.mention} a été retiré du ticket.")

@bot.tree.command(name="setup_liaison", description="[STAFF] Créer le bouton permanent de liaison")
@app_commands.default_permissions(manage_guild=True)
async def setup_liaison_cmd(interaction: discord.Interaction, salon: discord.TextChannel):
    embed = discord.Embed(title="🔗 Liaison de compte Steam", description="Associe ton compte Discord à ton SteamID pour suivre tes statistiques.", color=0xe63946)
    await salon.send(embed=embed, view=LierCompteView())
    await interaction.response.send_message(f"✅ Panneau généré dans {salon.mention}.", ephemeral=True)

@bot.tree.command(name="stats", description="Affiche tes statistiques")
async def voir_stats(interaction: discord.Interaction):
    pass # (Laissé vide ici car tu l'as déjà complet, garde ton code pour cette fonction)


# ==========================================
# GESTION WEB (FLASK)
# ==========================================
app = Flask('')
@app.route('/')
def home(): return "Bot en ligne !"
def run_flask(): app.run(host='0.0.0.0', port=8080)
Thread(target=run_flask).start()

bot.run(TOKEN)