import discord
from discord import app_commands
from discord.ext import commands, tasks
import pymysql
import os
from flask import Flask
from threading import Thread
# IMPORT MIS À JOUR POUR GÉRER L'HEURE DES ÉVÉNEMENTS
from datetime import datetime, time, timedelta, timezone 
import aiohttp
import re
import asyncio
import io 
import random
import google.generativeai as genai

# ==========================================
# CONFIGURATION DE BASE (TOKENS EN ENV, BDD EN DUR)
# ==========================================
TOKEN = os.environ.get('DISCORD_TOKEN', 'TON_TOKEN_DISCORD')
ID_SERVEUR_DISCORD = 1392952674604814487
IA_TOKEN = os.environ.get('IA_TOKEN', '')

# Mots de passe BDD en dur
DB_HOST = 'mysql-spicy-anomaly.alwaysdata.net'
DB_USER = 'spicy-anomaly_admin'
DB_PASS = 'p7$8FhKDQ@3xgxMb'
DB_NAME = 'spicy-anomaly_stats'

URL_API_STATUS = 'https://spicy-anomaly.alwaysdata.net/api_public.php'
URL_PANEL_WEB = "https://spicy-anomaly.alwaysdata.net"

NOM_ROLE_REPERE = "VIP"
NOM_SEPARATEUR = "─── Niveaux ───"
NOM_ROLE_LIE = "Lié"

# ==========================================
# LA BIBLE DE L'IA
# ==========================================
BIBLE_DU_SERVEUR = """
Tu es l'IA officielle et le copilote de 'Spicy Anomaly', un serveur SCP:SL francophone orienté E-Sport et Tryhard.
Ton but est de répondre aux questions des joueurs avec un ton amical, un peu d'humour, et d'aider le Staff avec précision.
Tu connais absolument TOUT du serveur, du site web, et du panel d'administration.

--- 1. LE SITE WEB (CÔTÉ JOUEUR) ---
- URL Officielle : https://spicy-anomaly.alwaysdata.net
- Classement : "Top XP" (Hall of Fame) et "Top Tueurs" (Ratio K/D).
- Profils : Les joueurs peuvent modifier leur fond d'écran au Niveau 5, ajouter une musique au Niveau 10, et un Badge exclusif au Niveau 15.
- Historique des sanctions : Un joueur peut aller dans l'onglet "Mes Sanctions" via son profil pour voir ses Warns, Mutes ou Bans, et soumettre un "Appel" pour contester.

--- 2. L'ÉCONOMIE, LES NIVEAUX ET LES QUÊTES ---
- Lier son compte : Obligatoire pour avoir ses stats (bouton Discord + SteamID64). /delier pour annuler.
- Gagner de l'XP : En jouant, en tuant, en s'échappant, et via les Quêtes.
- Les Quêtes : Les joueurs tapent .quetes en jeu ou /quetes sur Discord pour voir 3 missions quotidiennes.
- MVP de la Semaine : Dimanche à 20h00 UTC, le joueur avec le plus de 'weekly_xp' gagne le rôle "🌟 MVP de la Semaine" et une couronne sur le site web.

--- 3. LE PANEL D'ADMINISTRATION (CÔTÉ STAFF) ---
Si un membre du Staff te demande comment faire, guide-le via ces 6 onglets du Panel Web :
- 'Tickets IG' : Voir les signalements en jeu. Le staff peut "S'assigner" un ticket puis le "Clôturer".
- 'Casiers' : Chercher le SteamID d'un joueur pour voir son dossier (Warns, Mutes, Bans). Bouton "Sanctionner ce joueur" pour ajouter un Warn.
- 'Événements' : Créer une animation (Titre, Image, Desc, Date/Heure). Apparaît sur la page publique.
- 'Appels' : Bureau de contestation pour "Accepter (Lever la sanction)" ou "Refuser".
- 'Historique Global' : Tableau recensant toutes les sanctions.
- 'Efficacité Staff' : Classement interne des modérateurs.

--- 4. COMMANDES DISCORD POUR LE STAFF ---
- /warn : Avertir un joueur.
- /casier : Affiche le dossier d'un joueur sur Discord.
- /patchnote : Annonce une mise à jour (+, -, ~).
- /recrutement : Ouvre une campagne.

--- 5. RÈGLEMENT ---
- Interdictions : Alliances Inter-Factions, TK, Spawnkill (sauf zone Fondation), Combat Log, Bloquer 914.
"""

model_ia = None
model_parler = None
if IA_TOKEN:
    genai.configure(api_key=IA_TOKEN)
    model_ia = genai.GenerativeModel('gemini-3.6-flash')
    model_parler = genai.GenerativeModel('gemini-3.6-flash', system_instruction=BIBLE_DU_SERVEUR)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

CONFIG_CACHE = {}

def get_db_connection():
    return pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME, cursorclass=pymysql.cursors.DictCursor)

def init_db():
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("CREATE TABLE IF NOT EXISTS discord_config (config_key VARCHAR(50) PRIMARY KEY, config_value VARCHAR(255))")
            cursor.execute("CREATE TABLE IF NOT EXISTS player_quests (id INT AUTO_INCREMENT PRIMARY KEY, steamid VARCHAR(50), description VARCHAR(255), objectif INT, progression INT DEFAULT 0, xp_recompense INT, date_assignation DATE)")
            cursor.execute("CREATE TABLE IF NOT EXISTS player_infractions (id INT AUTO_INCREMENT PRIMARY KEY, steamid VARCHAR(50), type_sanction VARCHAR(50), reason VARCHAR(255), staff_pseudo VARCHAR(100), date_infraction TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.commit()
    except Exception as e: print(f"Erreur init DB: {e}")
    finally:
        if 'conn' in locals() and conn.open: conn.close()

def get_config(key, default=0):
    if key in CONFIG_CACHE: return CONFIG_CACHE[key]
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT config_value FROM discord_config WHERE config_key = %s", (key,))
            res = cursor.fetchone()
        val = int(res['config_value']) if res else default
        CONFIG_CACHE[key] = val
        return val
    except: return default
    finally:
        if 'conn' in locals() and conn.open: conn.close()

def set_config(key, value):
    CONFIG_CACHE[key] = int(value)
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO discord_config (config_key, config_value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE config_value = %s", (key, str(value), str(value)))
        conn.commit()
    except Exception as e: print(f"Erreur save config: {e}")
    finally:
        if 'conn' in locals() and conn.open: conn.close()

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
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
    }
    role_spicy = guild.get_role(get_config('ID_ROLE_SPICY_TEAM'))
    role_manager = guild.get_role(get_config('ID_ROLE_MANAGER'))
    
    if type_ticket == "recrutement":
        if role_spicy: overwrites[role_spicy] = discord.PermissionOverwrite(read_messages=False)
        if role_manager: overwrites[role_manager] = discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
    elif type_ticket == "support":
        if role_spicy: overwrites[role_spicy] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        if role_manager: overwrites[role_manager] = discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        
    return overwrites

async def process_ticket_closure(channel, closed_by, reason):
    messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
    transcript_raw = "".join([f"[{msg.created_at.strftime('%Y-%m-%d %H:%M')}] {msg.author.display_name}: {msg.clean_content}\n" for msg in messages])
    transcript_text = f"--- Transcript du salon {channel.name} ---\nDate: {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\nFermé par: {closed_by.display_name}\nRaison: {reason}\n\n" + transcript_raw

    ticket_owner = next((target for target, overwrite in channel.overwrites.items() if isinstance(target, discord.Member) and not target.bot and not overwrite.manage_channels), None)

    resume_ia = "Résumé non disponible."
    if model_ia and len(messages) > 2:
        try:
            response = await asyncio.to_thread(model_ia.generate_content, f"Résume ce ticket en 2 phrases pour les admins.\n\n{transcript_raw[-5000:]}")
            resume_ia = response.text.strip()
        except: pass

    if ticket_owner:
        try:
            embed_dm = discord.Embed(title=f"🔒 Ton ticket `{channel.name}` a été fermé", description=f"**Raison :** {reason}\n**Fermé par :** {closed_by.mention}", color=0xe74c3c)
            await ticket_owner.send(embed=embed_dm, file=discord.File(io.BytesIO(transcript_text.encode('utf-8')), filename=f"transcript-{channel.name}.txt"))
        except discord.Forbidden: pass

    salon_logs = get_config('ID_SALON_TRANSCRIPTS')
    if salon_logs:
        log_channel = channel.guild.get_channel(salon_logs)
        if log_channel:
            embed_log = discord.Embed(title=f"📄 Transcript : {channel.name}", description=f"**Fermé par :** {closed_by.mention}\n**Raison :** {reason}", color=0x2c3e50)
            if ticket_owner: embed_log.add_field(name="Propriétaire", value=ticket_owner.mention, inline=False)
            embed_log.add_field(name="🧠 Résumé de l'IA", value=f"*{resume_ia}*", inline=False)
            await log_channel.send(embed=embed_log, file=discord.File(io.BytesIO(transcript_text.encode('utf-8')), filename=f"{channel.name}.txt"))

    await asyncio.sleep(2)
    await channel.delete()


# ==========================================
# MENUS, VUES ET FORMULAIRES (UI)
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
        has_perm = interaction.user.guild_permissions.manage_channels
        if get_config('ID_ROLE_SPICY_TEAM') and discord.utils.get(interaction.user.roles, id=get_config('ID_ROLE_SPICY_TEAM')): has_perm = True
        if get_config('ID_ROLE_MANAGER') and discord.utils.get(interaction.user.roles, id=get_config('ID_ROLE_MANAGER')): has_perm = True
        if has_perm: await interaction.response.send_modal(ModalCloseTicket())
        else: await interaction.response.send_message("❌ Réservé au staff.", ephemeral=True)

class FAQCloseView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="✅ Ceci a résolu mon problème", style=discord.ButtonStyle.success, custom_id="faq_close_ticket")
    async def btn_faq_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔒 **Super ! Fermeture du ticket en cours...**")
        await process_ticket_closure(interaction.channel, interaction.user, "Résolu par l'Assistant IA.")

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
        nom_salon = f"candid-{self.prefixe}-{re.sub(r'[^a-z0-9]', '', interaction.user.display_name.lower()) or str(interaction.user.id)[:6]}"

        if discord.utils.get(guild.text_channels, name=nom_salon):
            return await interaction.followup.send(f"❌ Tu as déjà une candidature en cours.", ephemeral=True)

        try:
            ticket = await guild.create_text_channel(name=nom_salon, category=categorie, overwrites=get_ticket_overwrites(guild, interaction.user, "recrutement"))
            await interaction.followup.send(f"✅ Ticket créé : {ticket.mention}", ephemeral=True)
            embed = discord.Embed(title=f"🎫 Candidature : {self.role_nom}", description=f"Bienvenue {interaction.user.mention} !\n\n**Motivations :**\n```\n{self.motivations.value}\n```", color=0x3498db)
            role_manager_id = get_config('ID_ROLE_MANAGER')
            await ticket.send(content=f"{interaction.user.mention} | {f'<@&{role_manager_id}>' if role_manager_id else ''}", embed=embed, view=TicketCloseView())
        except Exception: await interaction.followup.send("❌ Erreur de création du ticket.", ephemeral=True)

class RecrutementPersistentView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Devenir Modérateur", style=discord.ButtonStyle.primary, custom_id="ticket_mod", emoji="🛡️")
    async def btn_mod(self, interaction: discord.Interaction, button: discord.ui.Button): await interaction.response.send_modal(ModalRecrutement("Modérateur", "mod"))
    @discord.ui.button(label="Devenir Animateur", style=discord.ButtonStyle.success, custom_id="ticket_anim", emoji="🎉")
    async def btn_anim(self, interaction: discord.Interaction, button: discord.ui.Button): await interaction.response.send_modal(ModalRecrutement("Animateur", "anim"))

class ModalSupport(discord.ui.Modal):
    def __init__(self, raison_choisie: str):
        super().__init__(title=f"Ticket : {raison_choisie}")
        self.raison_choisie = raison_choisie
        self.sujet = discord.ui.TextInput(label="Détaille ton problème", style=discord.TextStyle.paragraph, required=True)
        self.add_item(self.sujet)

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
            ticket = await guild.create_text_channel(name=nom_salon, category=categorie, overwrites=get_ticket_overwrites(guild, interaction.user, "support"))
            await interaction.followup.send(f"✅ Ticket créé : {ticket.mention}", ephemeral=True)
            
            embed = discord.Embed(title=f"🛠️ Ticket : {self.raison_choisie}", description=f"Bonjour {interaction.user.mention},\n\nUn membre du Staff va arriver pour t'aider.\n\n**Ton problème :**\n*{self.sujet.value}*", color=0xf1c40f)
            role_staff_id = get_config('ID_ROLE_SPICY_TEAM')
            mention_staff = f"<@&{role_staff_id}>" if role_staff_id else ""
            await ticket.send(content=f"{interaction.user.mention} {mention_staff}", embed=embed, view=TicketCloseView())

            async with ticket.typing():
                if "Appel de Sanction" in self.raison_choisie:
                    embed_auto = discord.Embed(title="🤖 Réponse Automatique", description=f"Pour contester une sanction, tu n'es pas au bon endroit !\n\nRends-toi sur notre **[Panel Web]({URL_PANEL_WEB})**, connecte-toi, clique sur ton profil puis sur **'Mes Sanctions'**. Tu pourras y rédiger ton appel officiel.", color=0xe74c3c)
                    await ticket.send(embed=embed_auto, view=FAQCloseView())
                    
                elif "Liaison" in self.raison_choisie:
                    embed_auto = discord.Embed(title="🤖 Réponse Automatique", description="Si tu as un bug avec la liaison de ton compte Steam :\n1. Tape la commande `/delier` ici sur Discord.\n2. Retourne sur le salon de liaison et recommence avec ton SteamID64.\n\n*Si ça ne marche toujours pas, un staff arrive.*", color=0x3498db)
                    await ticket.send(embed=embed_auto, view=FAQCloseView())
                    
                elif model_ia:
                    try:
                        system_prompt = f"Tu es l'IA de Spicy Anomaly. Un joueur ouvre un ticket dans la catégorie '{self.raison_choisie}'. Son message détaillé est : '{self.sujet.value}'. Réponds très concisément (3 phrases max) pour lui donner un conseil lié à son problème avant qu'un modérateur n'arrive."
                        resp = await asyncio.to_thread(model_ia.generate_content, system_prompt)
                        embed_ia = discord.Embed(title="🤖 1ère Réponse Automatique (IA)", description=resp.text.strip(), color=0x3498db)
                        await ticket.send(embed=embed_ia, view=FAQCloseView())
                    except Exception as ia_e:
                        print(f"Erreur IA générée : {ia_e}")
                        pass 
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur lors de la création : `{e}`", ephemeral=True)
            print(f"ERREUR TICKET FATALE : {e}")

class TicketReasonSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Problème de Liaison", emoji="🔗", description="Bug avec le bot ou ton compte Steam"),
            discord.SelectOption(label="Appel de Sanction", emoji="⚖️", description="Contester un avertissement, mute ou ban"),
            discord.SelectOption(label="Bug en jeu", emoji="🐛", description="Un problème technique sur le serveur SCP:SL"),
            discord.SelectOption(label="Question / Aide", emoji="❓", description="Une question sur le fonctionnement du serveur"),
            discord.SelectOption(label="Autre", emoji="📝", description="Toute autre demande")
        ]
        super().__init__(placeholder="Sélectionne la raison de ton ticket...", min_values=1, max_values=1, custom_id="select_ticket_reason", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ModalSupport(raison_choisie=self.values[0]))

class GeneralTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketReasonSelect())

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
                if not staff: return await interaction.response.send_message("❌ Compte Discord non lié.", ephemeral=True)
                cursor.execute("SELECT id, status FROM server_events_tickets WHERE discord_message_id = %s", (str(interaction.message.id),))
                ticket = cursor.fetchone()
                if not ticket: return await interaction.response.send_message("❌ Ticket introuvable.", ephemeral=True)
                if ticket['status'] in ['Pris', 'resolu', 'Résolu']: return await interaction.response.send_message("⚠️ Déjà pris.", ephemeral=True)
                
                cursor.execute("UPDATE server_events_tickets SET status = 'Pris', claimed_by = %s, claimed_steamid = %s WHERE id = %s", (staff['pseudo'], staff['steamid'], ticket['id']))
                conn.commit()
                embed = interaction.message.embeds[0]
                embed.color = 0xf39c12
                embed.add_field(name="🔄 Statut", value=f"Pris en charge par **{staff['pseudo']}**", inline=False)
                button.disabled = True
                await interaction.message.edit(embed=embed, view=self)
                await interaction.response.send_message("✅ Assigné.", ephemeral=True)
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
                cursor.execute("SELECT id FROM server_events_tickets WHERE discord_message_id = %s", (str(interaction.message.id),))
                ticket = cursor.fetchone()
                if ticket:
                    cursor.execute("UPDATE server_events_tickets SET status = 'resolu' WHERE id = %s", (ticket['id'],))
                    cursor.execute("UPDATE player_stats SET tickets_resolus = tickets_resolus + 1 WHERE steamid = %s", (staff['steamid'],))
                    conn.commit()
                    embed = interaction.message.embeds[0]
                    embed.color = 0x2ecc71
                    embed.add_field(name="✅ Statut", value="**Résolu**", inline=False)
                    for child in self.children:
                        if hasattr(child, 'style') and child.style != discord.ButtonStyle.link: child.disabled = True
                    await interaction.message.edit(embed=embed, view=self)
                    await interaction.response.send_message("✅ Clos.", ephemeral=True)
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
                    member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
                    if member:
                        role_lie = await get_or_create_role(interaction.guild, NOM_ROLE_LIE, discord.Color.green())
                        if role_lie: await member.add_roles(role_lie)
                        if user_data and user_data['pseudo']:
                            try: await member.edit(nick=user_data['pseudo'])
                            except discord.Forbidden: pass
                    await interaction.response.send_message(f"✅ Compte lié au SteamID `{steamid}`.", ephemeral=True)
                else: await interaction.response.send_message("❌ SteamID introuvable.", ephemeral=True)
        except Exception: await interaction.response.send_message("❌ Erreur BDD.", ephemeral=True)
        finally:
            if 'conn' in locals() and conn.open: conn.close()

class LierCompteView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🔗 Lier mon compte Steam", style=discord.ButtonStyle.success, custom_id="btn_lier_compte")
    async def btn_lier(self, interaction: discord.Interaction, button: discord.ui.Button): await interaction.response.send_modal(LierCompteModal())

# ==========================================
# LE BOT ET SES EVENEMENTS
# ==========================================
class SpicyBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=intents)
    async def setup_hook(self):
        init_db() 
        self.tree.copy_global_to(guild=discord.Object(id=ID_SERVEUR_DISCORD))
        await self.tree.sync(guild=discord.Object(id=ID_SERVEUR_DISCORD))
        self.add_view(RecrutementPersistentView())
        self.add_view(TicketCloseView())
        self.add_view(FAQCloseView())
        self.add_view(LierCompteView())
        self.add_view(TicketStaffView())
        self.add_view(GeneralTicketView()) 

bot = SpicyBot()

@bot.event
async def on_ready():
    print(f'✅ Bot connecté en tant que {bot.user} !')
    # On allume le check d'événements avec les autres
    for task in [check_levels_and_roles, update_server_status, update_live_leaderboard, check_new_tickets, election_mvp_hebdomadaire, check_new_events]:
        if not task.is_running(): task.start()

@bot.event
async def on_message(message):
    if message.author.bot: return
    await bot.process_commands(message)

@bot.event
async def on_member_join(member):
    if member.bot: return
    role_sep = await get_or_create_role(member.guild, NOM_SEPARATEUR, discord.Color.dark_grey())
    if role_sep and role_sep not in member.roles:
        try: await member.add_roles(role_sep)
        except: pass
    try: await member.send(embed=discord.Embed(title="👋 Bienvenue sur Spicy Anomaly !", description="Lie ton compte Steam pour suivre tes statistiques.", color=0xe63946), view=LierCompteView())
    except: pass

@tasks.loop(minutes=1)
async def update_server_status():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(URL_API_STATUS, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    status, players, max_p, players_list = data.get('status', 'offline'), data.get('players', 0), data.get('max', 20), data.get('players_list', [])
                    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{players}/{max_p} joueurs sur SCP:SL") if status == 'online' else discord.Game(name="🔴 Serveur Hors Ligne"))
                    salon_id = get_config('ID_SALON_STATUT')
                    if salon_id and (guild := bot.get_guild(ID_SERVEUR_DISCORD)) and (channel := guild.get_channel(salon_id)):
                        embed = discord.Embed(title="📊 Statut du Serveur SCP:SL", description=f"**État :** {'🟢 En ligne' if status == 'online' else '🔴 Hors ligne'}\n**Joueurs :** {players}/{max_p}", color=0x2ecc71 if status == 'online' else 0xe74c3c, timestamp=discord.utils.utcnow())
                        if players_list and status == 'online':
                            noms = ", ".join(players_list)
                            embed.add_field(name="En jeu actuellement", value=f"```\n{noms[:1018]}...\n```" if len(noms)>1024 else f"```\n{noms}\n```", inline=False)
                        embed.set_footer(text="Actualisé en temps réel")
                        last_msg = None
                        async for msg in channel.history(limit=5):
                            if msg.author == bot.user:
                                last_msg = msg; break
                        if last_msg: await last_msg.edit(embed=embed)
                        else: await channel.send(embed=embed)
    except: await bot.change_presence(activity=discord.Game(name="🔴 Serveur Hors Ligne"))

@tasks.loop(time=time(hour=20, minute=0))
async def election_mvp_hebdomadaire():
    if datetime.now().weekday() != 6: return 
    guild = bot.get_guild(ID_SERVEUR_DISCORD)
    if not guild: return
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT steamid, discord_id, pseudo, weekly_xp FROM player_stats WHERE discord_id IS NOT NULL ORDER BY weekly_xp DESC LIMIT 1")
            mvp = cursor.fetchone()
            if mvp and mvp['weekly_xp'] > 0:
                cursor.execute("UPDATE player_stats SET custom_badge = '🏆' WHERE steamid = %s", (mvp['steamid'],))
                cursor.execute("UPDATE player_stats SET custom_badge = NULL WHERE steamid != %s AND custom_badge = '🏆'", (mvp['steamid'],))
                role_mvp = await get_or_create_role(guild, "🌟 MVP de la Semaine", discord.Color.gold())
                for member in guild.members:
                    if role_mvp in member.roles and member.id != int(mvp['discord_id']): await member.remove_roles(role_mvp)
                if nouveau_mvp_member := guild.get_member(int(mvp['discord_id'])):
                    await nouveau_mvp_member.add_roles(role_mvp)
                    salon_id = get_config('ID_SALON_ANNONCES')
                    if salon_id and (salon_annonces := guild.get_channel(salon_id)):
                        await salon_annonces.send(content=f"🎉 {nouveau_mvp_member.mention}", embed=discord.Embed(title="🌟 MVP DE LA SEMAINE 🌟", description=f"Félicitations à **{mvp['pseudo']}** ({mvp['weekly_xp']} XP) !", color=discord.Color.gold()))
            cursor.execute("UPDATE player_stats SET weekly_xp = 0")
            conn.commit()
    except: pass
    finally:
        if 'conn' in locals() and conn.open: conn.close()

@tasks.loop(seconds=15)
async def check_new_tickets():
    salon_id = get_config('ID_SALON_TICKETS_STAFF')
    if not salon_id or not (guild := bot.get_guild(ID_SERVEUR_DISCORD)) or not (channel := guild.get_channel(salon_id)): return
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM server_events_tickets WHERE discord_message_id IS NULL AND (status = 'en attente' OR status = '')")
            for ticket in cursor.fetchall():
                embed = discord.Embed(title=f"🚨 Nouveau Signalement IG", description=f"**Signalé par:** `{ticket['reporter_pseudo']}`\n**Cible:** `{ticket['player_pseudo']}`", color=0xe74c3c)
                embed.add_field(name="Type", value=f"**{ticket['type_report']}**", inline=True); embed.add_field(name="Raison", value=f"_{ticket['reason']}_", inline=False)
                role_spicy_id = get_config('ID_ROLE_SPICY_TEAM')
                msg = await channel.send(content=f"Nouveau ticket ! {f'<@&{role_spicy_id}>' if role_spicy_id else ''}", embed=embed, view=TicketStaffView())
                cursor.execute("UPDATE server_events_tickets SET discord_message_id = %s WHERE id = %s", (str(msg.id), ticket['id']))
                conn.commit()
    except: pass
    finally:
        if 'conn' in locals() and conn.open: conn.close()

@tasks.loop(minutes=10)
async def update_live_leaderboard():
    salon_id = get_config('ID_SALON_CLASSEMENT')
    if not salon_id or not (guild := bot.get_guild(ID_SERVEUR_DISCORD)) or not (channel := guild.get_channel(salon_id)): return
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT pseudo, xp, level FROM player_stats ORDER BY level DESC, xp DESC LIMIT 10")
            top_xp = cursor.fetchall()
            cursor.execute("SELECT pseudo, kills, deaths FROM player_stats WHERE kills > 0 ORDER BY IF(deaths=0, kills, kills/deaths) DESC, kills DESC LIMIT 10")
            top_kills = cursor.fetchall()
        if not top_xp and not top_kills: return
        embed = discord.Embed(title="📊 CLASSEMENTS OFFICIELS SPICY ANOMALY", description=f"Mise à jour auto.\n🔗 **[Panel Web]({URL_PANEL_WEB})**", color=0xe63946, timestamp=discord.utils.utcnow())
        embed.add_field(name="🏆 Hall of Fame", value="".join([f"#{i+1} **{p['pseudo']}** • Niv. {p['level'] or 1} ({p['xp']:,} XP)\n" for i, p in enumerate(top_xp)]) or "Aucune donnée.", inline=False)
        embed.add_field(name="💀 Top 10 Tueurs", value="".join([f"#{i+1} **{p['pseudo']}** • **{p['kills']}** Kills\n" for i, p in enumerate(top_kills)]) or "Aucune donnée.", inline=False)
        async for msg in channel.history(limit=10):
            if msg.author == bot.user and msg.embeds and "CLASSEMENTS OFFICIELS" in msg.embeds[0].title: return await msg.edit(embed=embed)
        await channel.purge(limit=10)
        await channel.send(embed=embed)
    except: pass
    finally:
        if 'conn' in locals() and conn.open: conn.close()

@tasks.loop(minutes=5)
async def check_levels_and_roles():
    if not (guild := bot.get_guild(ID_SERVEUR_DISCORD)): return
    role_lie = await get_or_create_role(guild, NOM_ROLE_LIE, discord.Color.green())
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT discord_id, level, pseudo FROM player_stats WHERE discord_id IS NOT NULL")
            for j in cursor.fetchall():
                if member := guild.get_member(int(j['discord_id'])):
                    if role_lie and role_lie not in member.roles: await member.add_roles(role_lie)
                    if j['pseudo'] and member.display_name != j['pseudo'] and member.nick != j['pseudo']:
                        try: await member.edit(nick=j['pseudo'])
                        except: pass
                    palier = 1 if j['level'] < 5 else (j['level'] // 5) * 5
                    nom_role_cible = f"Niveau {palier}"
                    role_cible = await get_or_create_role(guild, nom_role_cible, discord.Color.teal())
                    roles_a_retirer = [r for r in member.roles if r.name.startswith("Niveau ") and r.name != nom_role_cible]
                    if roles_a_retirer: await member.remove_roles(*roles_a_retirer)
                    if role_cible and role_cible not in member.roles: await member.add_roles(role_cible)
    except: pass
    finally:
        if 'conn' in locals() and conn.open: conn.close()

# ⚠️ LA FONCTION AUTOMATIQUE PARFAITEMENT CORRIGÉE
@tasks.loop(minutes=2)
async def check_new_events():
    NOM_DE_LA_TABLE = "server_events" 
    
    salon_id = get_config('ID_SALON_ANNONCES')
    if not salon_id or not (guild := bot.get_guild(ID_SERVEUR_DISCORD)) or not (channel := guild.get_channel(salon_id)): return
    
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 1. On tente de créer la colonne de sécurité toute seule
            try:
                cursor.execute(f"ALTER TABLE {NOM_DE_LA_TABLE} ADD COLUMN annonce_postee TINYINT(1) DEFAULT 0")
                conn.commit()
            except: pass # Si elle existe déjà, on ignore

            # 2. On récupère les événements (On cherche bien 'annonce_postee = 0' !)
            cursor.execute(f"SELECT id, titre, description, date_event FROM {NOM_DE_LA_TABLE} WHERE annonce_postee = 0")
            evenements = cursor.fetchall()
            
            for ev in evenements:
                # 3. Sécurisation de l'heure (J'ai corrigé ev['date_heure'] qui faisait crasher !)
                date_ev = ev['date_event']
                if date_ev.tzinfo is None:
                    date_ev = date_ev.replace(tzinfo=timezone.utc)
                if date_ev < discord.utils.utcnow():
                    date_ev = discord.utils.utcnow() + timedelta(minutes=5)
                
                # 4. Création de l'Événement natif tout en haut du serveur Discord
                discord_event = await guild.create_scheduled_event(
                    name=ev['titre'],
                    description=ev['description'],
                    start_time=date_ev,
                    end_time=date_ev + timedelta(hours=2),
                    entity_type=discord.EntityType.external,
                    privacy_level=discord.PrivacyLevel.guild_only,
                    location="Serveur SCP:SL"
                )
                
                # 5. Envoi de l'embed avec le ping global
                embed = discord.Embed(title=f"🎉 {ev['titre']}", description=ev['description'], color=0x9b59b6, timestamp=date_ev)
                embed.add_field(name="🔗 Rejoindre l'événement", value=discord_event.url, inline=False)
                await channel.send(content="@everyone 📢 **Un nouvel événement a été programmé par le Staff !**", embed=embed)
                
                # 6. On coche la case pour ne plus jamais le renvoyer
                cursor.execute(f"UPDATE {NOM_DE_LA_TABLE} SET annonce_postee = 1 WHERE id = %s", (ev['id'],))
            
            conn.commit()
    except Exception as e:
        print(f"Erreur check_new_events : {e}")
    finally:
        if 'conn' in locals() and conn.open: conn.close()


# ==========================================
# COMMANDES SLASH
# ==========================================
@bot.tree.command(name="config_salon", description="[ADMIN] Définir dynamiquement un salon/catégorie")
@app_commands.default_permissions(manage_guild=True)
@app_commands.choices(type_salon=[app_commands.Choice(name="Catégorie Support", value="ID_CATEGORIE_SUPPORT"), app_commands.Choice(name="Catégorie Candidatures", value="ID_CATEGORIE_TICKETS"), app_commands.Choice(name="Salon Annonces MVP", value="ID_SALON_ANNONCES"), app_commands.Choice(name="Salon Classement", value="ID_SALON_CLASSEMENT"), app_commands.Choice(name="Salon Alerte Reports IG", value="ID_SALON_TICKETS_STAFF"), app_commands.Choice(name="Salon Statut", value="ID_SALON_STATUT"), app_commands.Choice(name="Salon Logs Transcripts", value="ID_SALON_TRANSCRIPTS"), app_commands.Choice(name="Salon Assistant Staff (IA)", value="ID_SALON_IA_STAFF")])
async def config_salon(interaction: discord.Interaction, type_salon: app_commands.Choice[str], salon: discord.abc.GuildChannel):
    set_config(type_salon.value, salon.id)
    await interaction.response.send_message(f"✅ Configurée : **{type_salon.name}** -> {salon.mention}", ephemeral=True)

@bot.tree.command(name="config_role", description="[ADMIN] Définir dynamiquement un rôle staff")
@app_commands.default_permissions(manage_guild=True)
@app_commands.choices(type_role=[app_commands.Choice(name="Rôle Spicy Team (Staff Global)", value="ID_ROLE_SPICY_TEAM"), app_commands.Choice(name="Rôle Manager (Perms Max)", value="ID_ROLE_MANAGER")])
async def config_role(interaction: discord.Interaction, type_role: app_commands.Choice[str], role: discord.Role):
    set_config(type_role.value, role.id)
    await interaction.response.send_message(f"✅ Configuré : **{type_role.name}** -> {role.mention}", ephemeral=True)

ticket_cmd_group = app_commands.Group(name="ticket", description="Gérer les tickets")
bot.tree.add_command(ticket_cmd_group)

@ticket_cmd_group.command(name="add", description="[STAFF] Ajouter un membre à ce ticket")
@app_commands.default_permissions(manage_messages=True)
async def ticket_add(interaction: discord.Interaction, membre: discord.Member):
    if "ticket" not in interaction.channel.name and "candid" not in interaction.channel.name: return await interaction.response.send_message("❌ Réservé aux tickets.", ephemeral=True)
    await interaction.channel.set_permissions(membre, read_messages=True, send_messages=True, attach_files=True)
    await interaction.response.send_message(f"✅ {membre.mention} a été ajouté.")

@ticket_cmd_group.command(name="remove", description="[STAFF] Retirer un membre de ce ticket")
@app_commands.default_permissions(manage_messages=True)
async def ticket_remove(interaction: discord.Interaction, membre: discord.Member):
    if "ticket" not in interaction.channel.name and "candid" not in interaction.channel.name: return await interaction.response.send_message("❌ Réservé aux tickets.", ephemeral=True)
    await interaction.channel.set_permissions(membre, overwrite=None)
    await interaction.response.send_message(f"✅ {membre.mention} a été retiré.")

@bot.tree.command(name="recrutement", description="[STAFF] Lancer une campagne de recrutement")
@app_commands.default_permissions(manage_guild=True)
async def recrutement_cmd(interaction: discord.Interaction, places_moderateur: int, places_animateur: int):
    embed = discord.Embed(title="📢 RECRUTEMENT OUVERT", description="Postulez via les boutons ci-dessous :", color=0xe63946)
    if places_moderateur > 0: embed.add_field(name="🛡️ Modérateur", value=f"{places_moderateur} places", inline=False)
    if places_animateur > 0: embed.add_field(name="🎉 Animateur", value=f"{places_animateur} places", inline=False)
    view = discord.ui.View(timeout=None)
    if places_moderateur > 0: view.add_item(discord.ui.Button(label="Devenir Modérateur", style=discord.ButtonStyle.primary, custom_id="ticket_mod"))
    if places_animateur > 0: view.add_item(discord.ui.Button(label="Devenir Animateur", style=discord.ButtonStyle.success, custom_id="ticket_anim"))
    await interaction.channel.send(content="@everyone", embed=embed, view=view)
    await interaction.response.send_message("✅ Fait.", ephemeral=True)

@bot.tree.command(name="warn", description="[STAFF] Avertir un joueur (Enregistré en BDD)")
@app_commands.default_permissions(manage_messages=True)
async def warn_user(interaction: discord.Interaction, membre: discord.Member, raison: str):
    role_spicy_id = get_config('ID_ROLE_SPICY_TEAM')
    if role_spicy_id and (role_spicy := interaction.guild.get_role(role_spicy_id)) and role_spicy in membre.roles and not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message("❌ Tu ne peux pas avertir le Staff.", ephemeral=True)
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT steamid FROM player_stats WHERE discord_id = %s", (str(membre.id),))
            if cible := cursor.fetchone():
                cursor.execute("INSERT INTO player_infractions (steamid, type_sanction, reason, staff_pseudo) VALUES (%s, %s, %s, %s)", (cible['steamid'], 'Warn', raison, interaction.user.display_name))
                cursor.execute("UPDATE player_stats SET warnings = warnings + 1 WHERE steamid = %s", (cible['steamid'],))
                conn.commit()
            embed = discord.Embed(title="⚠️ Nouvel Avertissement", color=0xe67e22)
            embed.add_field(name="Membre", value=membre.mention, inline=True); embed.add_field(name="Staff", value=interaction.user.mention, inline=True)
            embed.add_field(name="Raison", value=raison, inline=False)
            if not cible: embed.set_footer(text="Attention: Joueur non lié.")
            await interaction.response.send_message(embed=embed)
            try: await membre.send(embed=discord.Embed(title="⚠️ Tu as reçu un avertissement", description=f"**Raison :** {raison}", color=0xe74c3c))
            except: pass
    except Exception as e: await interaction.response.send_message(f"❌ Erreur: {e}", ephemeral=True)
    finally:
        if 'conn' in locals() and conn.open: conn.close()

@bot.tree.command(name="casier", description="[STAFF] Consulter le dossier disciplinaire complet d'un joueur")
@app_commands.default_permissions(manage_messages=True)
async def casier_staff(interaction: discord.Interaction, steamid: str):
    if not steamid.endswith('@steam'): steamid += '@steam'
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT pseudo, warnings, mutes, bans FROM player_stats WHERE steamid = %s", (steamid,))
            joueur = cursor.fetchone()
            if not joueur: return await interaction.response.send_message(f"❌ Aucun joueur trouvé.", ephemeral=True)
            
            cursor.execute("SELECT type_sanction, reason, staff_pseudo, DATE_FORMAT(date_infraction, '%%d/%%m/%%Y') as date_fmt FROM player_infractions WHERE steamid = %s ORDER BY date_infraction DESC LIMIT 5", (steamid,))
            infractions = cursor.fetchall()
            
            embed = discord.Embed(title=f"📁 Casier de {joueur['pseudo']}", description=f"`{steamid}`", color=0x34495e)
            embed.add_field(name="⚠️ Warns", value=f"**{joueur['warnings']}**", inline=True); embed.add_field(name="🔇 Mutes", value=f"**{joueur['mutes']}**", inline=True); embed.add_field(name="🔨 Bans", value=f"**{joueur['bans']}**", inline=True)
            if infractions:
                history_text = "".join([f"**{inf['type_sanction']}** par {inf['staff_pseudo']} ({inf['date_fmt']})\n└ {inf['reason']}\n\n" for inf in infractions])
                embed.add_field(name="Dernières infractions", value=history_text, inline=False)
            else: embed.add_field(name="Dernières infractions", value="✅ Casier vierge.", inline=False)
            await interaction.response.send_message(embed=embed)
    except Exception as e: await interaction.response.send_message(f"❌ Erreur: {e}", ephemeral=True)
    finally:
        if 'conn' in locals() and conn.open: conn.close()

@bot.tree.command(name="patchnote", description="[STAFF] Publier une mise à jour")
@app_commands.default_permissions(manage_guild=True)
async def patchnote_cmd(interaction: discord.Interaction, salon: discord.TextChannel, version: str, notes_brutes: str, ping_everyone: bool = False, role_a_ping: discord.Role = None):
    ajouts, retraits, modifs = [], [], []
    for ligne in notes_brutes.replace(',', '\n').split('\n'):
        ligne = ligne.strip()
        if ligne.startswith('+'): ajouts.append(f"✅ {ligne[1:].strip()}")
        elif ligne.startswith('-'): retraits.append(f"❌ {ligne[1:].strip()}")
        elif ligne.startswith('~'): modifs.append(f"🔄 {ligne[1:].strip()}")
        elif ligne: modifs.append(f"🔹 {ligne}")

    embed = discord.Embed(title=f"🚀 Mise à jour | Version {version}", color=0x2ecc71)
    if ajouts: embed.add_field(name="🟢 Nouveautés", value="\n".join(ajouts), inline=False)
    if modifs: embed.add_field(name="🟡 Changements", value="\n".join(modifs), inline=False)
    if retraits: embed.add_field(name="🔴 Retraits", value="\n".join(retraits), inline=False)
    
    mentions = []
    if ping_everyone: mentions.append("@everyone") 
    if role_a_ping: mentions.append(role_a_ping.mention)
    texte_mention = " ".join(mentions)

    await salon.send(content=texte_mention, embed=embed)
    await interaction.response.send_message("✅ Patch note publié avec succès.", ephemeral=True)

@bot.tree.command(name="ticket_setup", description="[STAFF] Créer un panel de tickets support")
@app_commands.default_permissions(manage_guild=True)
async def ticket_setup(interaction: discord.Interaction, salon: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    try:
        embed = discord.Embed(title="Besoin d'aide ?", description="Sélectionne la raison de ta demande via le menu ci-dessous pour ouvrir un ticket.", color=0x3498db)
        await salon.send(embed=embed, view=GeneralTicketView())
        await interaction.followup.send(f"✅ Panel généré avec succès dans {salon.mention} !", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(f"❌ **Erreur Permissions** : Le bot n'a pas le droit d'envoyer des messages ou d'Intégrer des liens dans {salon.mention}.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)

@bot.tree.command(name="setup_liaison", description="[STAFF] Créer le bouton de liaison")
@app_commands.default_permissions(manage_guild=True)
async def setup_liaison_cmd(interaction: discord.Interaction, salon: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    try:
        await salon.send(embed=discord.Embed(title="🔗 Liaison de compte", description="Associe ton Discord à ton SteamID.", color=0xe63946), view=LierCompteView())
        await interaction.followup.send(f"✅ Panneau généré dans {salon.mention}.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)

@bot.tree.command(name="parler", description="Pose n'importe quelle question sur le serveur à l'IA !")
async def parler_ia(interaction: discord.Interaction, question: str):
    if not model_parler: return await interaction.response.send_message("❌ IA désactivée.", ephemeral=True)
    await interaction.response.defer() 
    try:
        reponse = await asyncio.to_thread(model_parler.generate_content, question)
        question_safe = question[:1020] + "..." if len(question) > 1024 else question
        texte_ia = reponse.text.strip()
        if len(texte_ia) > 4000: texte_ia = texte_ia[:4000] + "..."
        embed = discord.Embed(title="🤖 Assistant IA", description=texte_ia, color=0x3498db)
        embed.add_field(name="🗣️ Ta question", value=question_safe, inline=False)
        await interaction.followup.send(embed=embed)
    except Exception as e: 
        erreur = str(e)
        if "429" in erreur or "quota" in erreur.lower():
            await interaction.followup.send("⏳ **L'IA est un peu surchargée (limite de requêtes atteinte). Attends une petite minute avant de relancer !**", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ Erreur technique: {erreur}", ephemeral=True)

@bot.tree.command(name="quetes", description="Affiche tes missions quotidiennes pour gagner de l'XP !")
async def voir_quetes(interaction: discord.Interaction):
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT steamid, pseudo FROM player_stats WHERE discord_id = %s", (str(interaction.user.id),))
            joueur = cursor.fetchone()
            if not joueur: return await interaction.response.send_message("❌ Compte non lié.", ephemeral=True)
            steamid, aujourdhui = joueur['steamid'], datetime.now().date()
            cursor.execute("SELECT * FROM player_quests WHERE steamid = %s AND date_assignation = %s", (steamid, aujourdhui))
            quetes = cursor.fetchall()
            if not quetes:
                cursor.execute("DELETE FROM player_quests WHERE steamid = %s", (steamid,))
                QT = [{"d": "Éliminer des SCP", "o": 3, "x": 800}, {"d": "S'échapper", "o": 1, "x": 500}, {"d": "Kills totaux", "o": 10, "x": 400}, {"d": "Survivre 15 min", "o": 1, "x": 400}]
                for q in random.sample(QT, 3): cursor.execute("INSERT INTO player_quests (steamid, description, objectif, xp_recompense, date_assignation) VALUES (%s, %s, %s, %s, %s)", (steamid, q['d'], q['o'], q['x'], aujourdhui))
                conn.commit(); cursor.execute("SELECT * FROM player_quests WHERE steamid = %s AND date_assignation = %s", (steamid, aujourdhui)); quetes = cursor.fetchall()
            
            embed = discord.Embed(title=f"🎯 Quêtes Quotidiennes de {joueur['pseudo']}", color=0xf39c12)
            for q in quetes:
                statut = "✅ Terminé" if q['progression'] >= q['objectif'] else f"⏳ ({q['progression']}/{q['objectif']})"
                embed.add_field(name=f"📜 {q['description']}", value=f"**Récompense :** ✨ {q['xp_recompense']} XP\n**Statut :** {statut}", inline=False)
            await interaction.response.send_message(embed=embed)
    except Exception as e: await interaction.response.send_message("❌ Erreur BDD.", ephemeral=True)
    finally:
        if 'conn' in locals() and conn.open: conn.close()

@bot.tree.command(name="delier", description="Retirer la liaison entre ton compte Discord et Steam")
async def delier_cmd(interaction: discord.Interaction):
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            if cursor.execute("UPDATE player_stats SET discord_id = NULL WHERE discord_id = %s", (str(interaction.user.id),)) > 0:
                conn.commit()
                role_lie = discord.utils.get(interaction.guild.roles, name=NOM_ROLE_LIE)
                if role_lie and role_lie in interaction.user.roles: await interaction.user.remove_roles(role_lie)
                await interaction.response.send_message("✅ Compte délié.", ephemeral=True)
            else: await interaction.response.send_message("❌ Non lié.", ephemeral=True)
    except Exception: await interaction.response.send_message("❌ Erreur.", ephemeral=True)
    finally:
        if 'conn' in locals() and conn.open: conn.close()

@bot.tree.command(name="stats", description="Affiche tes statistiques")
async def voir_stats(interaction: discord.Interaction):
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT pseudo, xp, level, kills, deaths FROM player_stats WHERE discord_id = %s", (str(interaction.user.id),))
            joueur = cursor.fetchone()
            if joueur:
                kd = f"{(joueur['kills']/(joueur['deaths'] or 1)):.2f}"
                embed = discord.Embed(title=f"📊 Stats de {joueur['pseudo']}", color=0xe63946)
                embed.add_field(name="Niveau", value=f"⭐ {joueur['level']}", inline=True); embed.add_field(name="XP", value=f"✨ {joueur['xp']} XP", inline=True); embed.add_field(name="Ratio K/D", value=f"📈 {kd}", inline=True)
                await interaction.response.send_message(embed=embed)
            else: await interaction.response.send_message("❌ Non lié.", ephemeral=True)
    finally:
        if 'conn' in locals() and conn.open: conn.close()

@bot.tree.command(name="profil", description="Affiche ton profil complet")
async def voir_profil(interaction: discord.Interaction):
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM player_stats WHERE discord_id = %s", (str(interaction.user.id),))
            if joueur := cursor.fetchone():
                kd = f"{(joueur['kills']/(joueur['deaths'] or 1)):.2f}"
                embed = discord.Embed(title=f"👤 Profil de {joueur['pseudo']}", color=0x3498db)
                embed.add_field(name="⭐ Niveau", value=f"{joueur['level']}", inline=True); embed.add_field(name="✨ XP", value=f"{joueur['xp']:,}", inline=True); embed.add_field(name="📈 K/D", value=f"{kd}", inline=True)
                embed.add_field(name="💀 Kills", value=f"{joueur['kills']}", inline=True); embed.add_field(name="🚪 Escapes", value=f"{joueur.get('escapes', 0)}", inline=True)
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
                await interaction.response.send_message(embed=embed)
            else: await interaction.response.send_message("❌ Non lié.", ephemeral=True)
    finally:
        if 'conn' in locals() and conn.open: conn.close()

app = Flask('')
@app.route('/')
def home(): return "Bot en ligne !"
def run_flask(): app.run(host='0.0.0.0', port=8080)
Thread(target=run_flask).start()

bot.run(TOKEN)