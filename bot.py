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

# Optionnel : ID de la catégorie où les tickets de recrutement seront créés
try:
    ID_CATEGORIE_TICKETS = int(os.environ.get('ID_CATEGORIE_TICKETS', 0))
except (TypeError, ValueError):
    ID_CATEGORIE_TICKETS = 0

NOM_ROLE_REPERE = "VIP"
NOM_SEPARATEUR = "─── Niveaux ───"

DB_HOST = os.environ.get('DB_HOST', 'mysql-spicy-anomaly.alwaysdata.net')
DB_USER = os.environ.get('DB_USER', 'spicy-anomaly_admin')
DB_PASS = os.environ.get('DB_PASS', 'p7$8FhKDQ@3xgxMb')
DB_NAME = os.environ.get('DB_NAME', 'spicy-anomaly_stats')

# L'URL de ton API existante (celle utilisée par ton site web)
URL_API_STATUS = os.environ.get('URL_API_STATUS', 'https://spicy-anomaly.alwaysdata.net/api_public.php')

intents = discord.Intents.default()
intents.members = True

# ==========================================
# VUES PERSISTANTES (Boutons Tickets)
# ==========================================

class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket", emoji="🔒")
    async def btn_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Seul un admin ou membre du staff (gérant les salons) peut fermer
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

        # Nettoyage du pseudo pour le nom du channel (lettres minuscules et chiffres uniquement)
        pseudo_clean = re.sub(r'[^a-z0-9]', '', interaction.user.display_name.lower())
        if not pseudo_clean:
            pseudo_clean = str(interaction.user.id)[:6]
            
        nom_salon = f"ticket-{prefixe}-{pseudo_clean}"
        
        # Vérification si le ticket existe déjà
        existant = discord.utils.get(guild.text_channels, name=nom_salon)
        if existant:
            await interaction.response.send_message(f"❌ Tu as déjà un ticket d'ouvert : {existant.mention}", ephemeral=True)
            return

        # Permissions : Le bot + l'utilisateur + les Admins
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }

        try:
            ticket = await guild.create_text_channel(name=nom_salon, category=categorie, overwrites=overwrites, reason=f"Ticket recrutement {role_nom}")
            await interaction.response.send_message(f"✅ Ton ticket a été créé : {ticket.mention}", ephemeral=True)
            
            embed = discord.Embed(
                title=f"🎫 Candidature {role_nom}",
                description=f"Bienvenue {interaction.user.mention} !\n\nL'équipe administrative traitera ta demande sous peu. En attendant, merci de préparer ta candidature ou de lister tes motivations ci-dessous.",
                color=0x2ecc71 if prefixe == "anim" else 0x3498db
            )
            
            await ticket.send(f"{interaction.user.mention} | Candidature", embed=embed, view=TicketCloseView())
        except Exception as e:
            await interaction.response.send_message("❌ Erreur lors de la création du ticket. Contacte un administrateur.", ephemeral=True)
            print(f"Erreur Ticket: {e}")

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
        
        # Enregistrer les vues pour qu'elles restent actives après un redémarrage du bot !
        self.add_view(RecrutementView())
        self.add_view(TicketCloseView())
        
        print("🔄 Commandes Slash (/) et Vues synchronisées avec succès !")

bot = SpicyBot()

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
            role = await guild.create_role(name=role_name, color=color, reason="Création auto système de niveau")
            print(f"✨ Nouveau rôle créé : {role_name}")
            role_repere = discord.utils.get(guild.roles, name=NOM_ROLE_REPERE)
            if role_repere and guild.me.top_role.position > role_repere.position:
                new_position = max(1, role_repere.position - 1)
                await role.edit(position=new_position)
        except Exception as e:
            print(f"Erreur création rôle {role_name}: {e}")
    return role

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

@bot.event
async def on_member_join(member):
    if member.bot: return
    role_sep = await get_or_create_role(member.guild, NOM_SEPARATEUR, discord.Color.dark_grey())
    if role_sep and role_sep not in member.roles:
        try:
            await member.add_roles(role_sep)
        except discord.Forbidden:
            pass

@tasks.loop(minutes=1)
async def update_server_status():
    """Met à jour le statut du bot via l'API publique du Panel Web"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(URL_API_STATUS, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('status') == 'online':
                        players = data.get('players', 0)
                        max_p = data.get('max', 20)
                        # Affiche : "Regarde 12/20 joueurs sur SCP:SL"
                        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{players}/{max_p} joueurs sur SCP:SL"))
                    else:
                        await bot.change_presence(activity=discord.Game(name="🔴 Serveur Hors Ligne"))
                else:
                    await bot.change_presence(activity=discord.Game(name="🔴 Serveur Hors Ligne"))
    except Exception:
        await bot.change_presence(activity=discord.Game(name="🔴 Serveur Hors Ligne"))

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
                event_db_id = ev['id']
                
                tz = pytz.timezone('Europe/Paris')
                try:
                    start_time = datetime.strptime(str(ev['date_event']), '%Y-%m-%dT%H:%M')
                    start_time = tz.localize(start_time)
                except:
                    start_time = datetime.now(tz) + timedelta(minutes=10)

                if start_time < datetime.now(tz):
                    start_time = datetime.now(tz) + timedelta(minutes=5)
                
                end_time = start_time + timedelta(hours=2)

                cursor.execute("UPDATE server_events SET discord_event_id = 'PENDING' WHERE id = %s", (event_db_id,))
                conn.commit()

                raw_image_url = ev.get('image_url')
                valid_image_url = None
                image_bytes = None

                if raw_image_url and isinstance(raw_image_url, str):
                    clean_url = raw_image_url.strip()
                    if is_valid_url(clean_url):
                        valid_image_url = clean_url
                        try:
                            async with aiohttp.ClientSession() as session:
                                async with session.get(valid_image_url) as resp:
                                    if resp.status == 200:
                                        image_bytes = await resp.read()
                        except Exception as img_err:
                            print(f"⚠️ Impossible de télécharger l'image: {img_err}")

                try:
                    event_kwargs = {
                        "name": f"🎉 {ev['titre']}",
                        "description": f"{ev['description']}\n\n👥 Supervisé par : **{ev['staff_implique']}**",
                        "start_time": start_time,
                        "end_time": end_time,
                        "entity_type": discord.EntityType.external,
                        "location": "Serveur Spicy Anomaly",
                        "privacy_level": discord.PrivacyLevel.guild_only
                    }

                    if image_bytes:
                        event_kwargs["image"] = image_bytes

                    discord_event = await guild.create_scheduled_event(**event_kwargs)

                    salon = guild.get_channel(ID_SALON_ANNONCES)
                    if salon:
                        embed = discord.Embed(
                            title=f"🚨 NOUVEL ÉVÉNEMENT : {ev['titre']}",
                            description=f"{ev['description']}\n\n👉 **[Clique ici pour t'inscrire et recevoir une alerte !]({discord_event.url})**",
                            color=0xe63946
                        )
                        if valid_image_url:
                            embed.set_image(url=valid_image_url)
                            
                        embed.set_footer(text=f"Organisé par {ev['staff_implique']}")
                        await salon.send("@everyone", embed=embed)

                    cursor.execute("UPDATE server_events SET discord_event_id = %s WHERE id = %s", (str(discord_event.id), event_db_id))
                    conn.commit()

                except Exception as ex:
                    print(f"Erreur création événement Discord : {ex}")
                    cursor.execute("UPDATE server_events SET discord_event_id = NULL WHERE id = %s", (event_db_id,))
                    conn.commit()

    except Exception as e:
        print(f"Erreur DB check events: {e}")
    finally:
        if 'conn' in locals() and conn.open:
            conn.close()

# ==========================================
# COMMANDES SLASH (/)
# ==========================================

@bot.tree.command(name="recrutement", description="[STAFF] Gérer l'annonce de recrutement et générer les boutons de tickets")
@app_commands.describe(
    salon="Le salon Discord où envoyer l'annonce",
    message="Le texte d'introduction de l'annonce",
    besoin_modo="Recherche-t-on actuellement des Modérateurs ?",
    besoin_anim="Recherche-t-on actuellement des Animateurs ?"
)
@app_commands.default_permissions(manage_guild=True) # Réservé aux personnes pouvant gérer le serveur
async def recrutement_cmd(interaction: discord.Interaction, salon: discord.TextChannel, message: str, besoin_modo: bool, besoin_anim: bool):
    
    embed = discord.Embed(
        title="📢 CAMPAGNE DE RECRUTEMENT",
        description=message + "\n\n*Cliquez sur les boutons ci-dessous pour ouvrir un ticket de candidature exclusif et privé avec l'équipe administrative.*",
        color=0xff3b3b
    )
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
    
    recherche_texte = ""
    if besoin_modo:
        recherche_texte += "🛡️ **Modérateur** : OUVERT\n"
    if besoin_anim:
        recherche_texte += "🎉 **Animateur** : OUVERT\n"
        
    if recherche_texte:
        embed.add_field(name="Postes actuellement à pourvoir :", value=recherche_texte, inline=False)
    else:
        embed.add_field(name="Postes à pourvoir :", value="❌ Fermé pour le moment.", inline=False)
        
    view = RecrutementView()
    
    # On retire les boutons dynamiquement si le rôle n'est pas recherché
    if not besoin_modo:
        btn = discord.utils.get(view.children, custom_id="ticket_mod")
        if btn: view.remove_item(btn)
    if not besoin_anim:
        btn = discord.utils.get(view.children, custom_id="ticket_anim")
        if btn: view.remove_item(btn)
        
    try:
        await salon.send(content="🔔 @everyone", embed=embed, view=view)
        await interaction.response.send_message(f"✅ L'annonce de recrutement a été générée avec succès dans {salon.mention}.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Je n'ai pas la permission d'envoyer un message dans ce salon.", ephemeral=True)


@bot.tree.command(name="lier", description="Lie ton compte Discord à ton SteamID64")
@app_commands.describe(steamid="Ton SteamID64 (ex: 7656119...)")
async def lier_compte(interaction: discord.Interaction, steamid: str):
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
                await interaction.response.send_message(f"✅ Ton compte Discord a été lié au SteamID `{steamid}` !", ephemeral=True)
            else:
                await interaction.response.send_message("❌ SteamID introuvable dans la base de données.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message("❌ Erreur de base de données.", ephemeral=True)
    finally:
        if 'conn' in locals() and conn.open:
            conn.close()


@bot.tree.command(name="stats", description="Affiche tes statistiques")
async def voir_stats(interaction: discord.Interaction):
    discord_id = str(interaction.user.id)
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT pseudo, xp, level, kills, escapes FROM player_stats WHERE discord_id = %s", (discord_id,))
            joueur = cursor.fetchone()
            if joueur:
                embed = discord.Embed(
                    title=f"📊 Statistiques de {joueur['pseudo']}",
                    url="https://spicy-anomaly.alwaysdata.net",
                    color=0xe63946
                )
                embed.add_field(name="Niveau", value=f"⭐ {joueur['level']}", inline=True)
                embed.add_field(name="XP Total", value=f"✨ {joueur['xp']} XP", inline=True)
                embed.add_field(name="Kills", value=f"💀 {joueur['kills']}", inline=True)
                embed.add_field(name="Évasions", value=f"🏃 {joueur['escapes']}", inline=True)
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("❌ Ton compte n'est pas lié.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message("❌ Erreur de base de données.", ephemeral=True)
    finally:
        if 'conn' in locals() and conn.open:
            conn.close()


@tasks.loop(minutes=5)
async def check_levels_and_roles():
    guild = bot.get_guild(ID_SERVEUR_DISCORD)
    if not guild: return
    role_sep = await get_or_create_role(guild, NOM_SEPARATEUR, discord.Color.dark_grey())
    if role_sep:
        for member in guild.members:
            if not member.bot and role_sep not in member.roles:
                try:
                    await member.add_roles(role_sep)
                except: pass
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT discord_id, level FROM player_stats WHERE discord_id IS NOT NULL")
            joueurs = cursor.fetchall()
            for j in joueurs:
                member = guild.get_member(int(j['discord_id']))
                if not member: continue
                lvl = j['level']
                palier = 1 if lvl < 5 else (lvl // 5) * 5
                nom_role_cible = f"Niveau {palier}"
                role_cible = await get_or_create_role(guild, nom_role_cible, discord.Color.teal())
                roles_a_retirer = [r for r in member.roles if r.name.startswith("Niveau ") and r.name != nom_role_cible]
                if roles_a_retirer:
                    await member.remove_roles(*roles_a_retirer)
                if role_cible and role_cible not in member.roles:
                    await member.add_roles(role_cible)
    except Exception as e:
        print(f"Erreur rôles: {e}")
    finally:
        if 'conn' in locals() and conn.open:
            conn.close()


app = Flask('')
@app.route('/')
def home():
    return "Le bot est en ligne !"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

t = Thread(target=run_flask)
t.start()

bot.run(TOKEN)