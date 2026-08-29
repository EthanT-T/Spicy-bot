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

# ==========================================
# CONFIGURATION (Via Variables d'Environnement)
# ==========================================

TOKEN = os.environ.get('DISCORD_TOKEN')

# Sécurisation et récupération des IDs (avec valeurs par défaut de secours)
try:
    ID_SERVEUR_DISCORD = int(os.environ.get('ID_SERVEUR_DISCORD', 1392952674604814487))
except (TypeError, ValueError):
    ID_SERVEUR_DISCORD = 1392952674604814487

try:
    ID_SALON_ANNONCES = int(os.environ.get('ID_SALON_ANNONCES', 0))
except (TypeError, ValueError):
    ID_SALON_ANNONCES = 0

NOM_ROLE_REPERE = "VIP"                    # Nom exact du rôle sous lequel placer les niveaux
NOM_SEPARATEUR = "─── Niveaux ───"         # Nom du rôle séparateur

# Configuration MySQL
DB_HOST = os.environ.get('DB_HOST', 'mysql-spicy-anomaly.alwaysdata.net')
DB_USER = os.environ.get('DB_USER', 'spicy-anomaly_admin')
DB_PASS = os.environ.get('DB_PASS', 'p7$8FhKDQ@3xgxMb')
DB_NAME = os.environ.get('DB_NAME', 'spicy-anomaly_stats')

intents = discord.Intents.default()
intents.members = True  # Indispensable pour scanner les membres !

class SpicyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        guild = discord.Object(id=ID_SERVEUR_DISCORD)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print("🔄 Commandes Slash (/) synchronisées avec succès !")

bot = SpicyBot()

def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor
    )

# ==========================================
# GESTION DYNAMIQUE DES RÔLES
# ==========================================

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
        except discord.Forbidden:
            print(f"⚠️ Permissions insuffisantes pour créer/placer le rôle {role_name}")
        except Exception as e:
            print(f"Erreur création rôle {role_name}: {e}")
            
    return role

# ==========================================
# ÉVÉNEMENTS DU BOT
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

# ==========================================
# STATUT DYNAMIQUE DU BOT
# ==========================================

@tasks.loop(minutes=1)
async def update_server_status():
    """Met à jour le statut du bot (Jeu / Activité)"""
    try:
        conn = get_db_connection()
        # Test simple de connexion à la BDD pour valider que le serveur web/BDD répond
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
        await bot.change_presence(activity=discord.Game(name="SCP: Secret Laboratory"))
    except Exception as e:
        await bot.change_presence(activity=discord.Game(name="🔴 Serveur Hors Ligne"))
    finally:
        if 'conn' in locals() and conn.open:
            conn.close()

# ==========================================
# CRÉATION AUTOMATIQUE D'ÉVÉNEMENTS
# ==========================================

@tasks.loop(minutes=1)
async def check_new_events():
    guild = bot.get_guild(ID_SERVEUR_DISCORD)
    if not guild: return

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # On cherche les événements non postés
            cursor.execute("SELECT * FROM server_events WHERE discord_event_id IS NULL OR discord_event_id = ''")
            new_events = cursor.fetchall()

            for ev in new_events:
                event_db_id = ev['id']
                
                # 1. Préparation de la date (Heure de Paris)
                tz = pytz.timezone('Europe/Paris')
                try:
                    start_time = datetime.strptime(str(ev['date_event']), '%Y-%m-%dT%H:%M')
                    start_time = tz.localize(start_time)
                except:
                    start_time = datetime.now(tz) + timedelta(minutes=10)

                if start_time < datetime.now(tz):
                    start_time = datetime.now(tz) + timedelta(minutes=5)
                
                end_time = start_time + timedelta(hours=2)

                # 2. VERROUILLAGE BDD : Empêche les boucles et doublons en marquant 'PENDING'
                cursor.execute("UPDATE server_events SET discord_event_id = 'PENDING' WHERE id = %s", (event_db_id,))
                conn.commit()

                # 3. Récupération optionnelle de l'image en bytes
                image_bytes = None
                if ev.get('image_url') and ev['image_url'].strip() != "":
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(ev['image_url']) as resp:
                                if resp.status == 200:
                                    image_bytes = await resp.read()
                    except Exception as img_err:
                        print(f"⚠️ Impossible de charger l'image de l'événement: {img_err}")

                # 4. Création de l'événement natif Discord
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

                    # 5. Message d'annonce dans le salon configuré (ID_SALON_ANNONCES)
                    salon = guild.get_channel(ID_SALON_ANNONCES)
                    if salon:
                        embed = discord.Embed(
                            title=f"🚨 NOUVEL ÉVÉNEMENT : {ev['titre']}",
                            description=f"{ev['description']}\n\n👉 **[Clique ici pour t'inscrire et recevoir une alerte !]({discord_event.url})**",
                            color=0xe63946
                        )
                        if ev.get('image_url') and ev['image_url'].strip() != "":
                            embed.set_image(url=ev['image_url'])
                        embed.set_footer(text=f"Organisé par {ev['staff_implique']}")
                        await salon.send("@everyone", embed=embed)

                    # 6. Sauvegarde du vrai ID Discord de l'événement
                    cursor.execute("UPDATE server_events SET discord_event_id = %s WHERE id = %s", (str(discord_event.id), event_db_id))
                    conn.commit()
                    print(f"🎉 Événement {ev['titre']} créé avec succès sur Discord !")

                except Exception as ex:
                    print(f"Erreur création événement Discord : {ex}")
                    # En cas d'échec, on remet à NULL pour retenter plus tard
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
                await interaction.response.send_message("❌ SteamID introuvable dans la base de données. Connecte-toi au serveur de jeu d'abord !", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message("❌ Erreur de connexion à la base de données.", ephemeral=True)
        print(e)
    finally:
        if 'conn' in locals() and conn.open:
            conn.close()

@bot.tree.command(name="stats", description="Affiche tes statistiques et ton niveau sur Spicy Anomaly")
async def voir_stats(interaction: discord.Interaction):
    discord_id = str(interaction.user.id)
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT pseudo, xp, level, kills, escapes FROM player_stats WHERE discord_id = %s"
            cursor.execute(sql, (discord_id,))
            joueur = cursor.fetchone()
            
            if joueur:
                embed = discord.Embed(
                    title=f"📊 Statistiques de {joueur['pseudo']}",
                    url="https://spicy-anomaly.alwaysdata.net",
                    description="🔗 **[Voir le classement complet sur le Panel Web](https://spicy-anomaly.alwaysdata.net)**", 
                    color=0xe63946
                )
                embed.add_field(name="Niveau", value=f"⭐ {joueur['level']}", inline=True)
                embed.add_field(name="XP Total", value=f"✨ {joueur['xp']} XP", inline=True)
                embed.add_field(name="Kills", value=f"💀 {joueur['kills']}", inline=True)
                embed.add_field(name="Évasions", value=f"🏃 {joueur['escapes']}", inline=True)
                embed.set_footer(text="Spicy Anomaly - Serveur TryHard")
                
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("❌ Ton compte n'est pas lié. Fais `/lier` avec ton SteamID d'abord !", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message("❌ Erreur de base de données.", ephemeral=True)
        print(e)
    finally:
        if 'conn' in locals() and conn.open:
            conn.close()

# ==========================================
# BOUCLE D'ACTUALISATION DES NIVEAUX
# ==========================================

@tasks.loop(minutes=5)
async def check_levels_and_roles():
    guild = bot.get_guild(ID_SERVEUR_DISCORD)
    if not guild:
        return

    role_sep = await get_or_create_role(guild, NOM_SEPARATEUR, discord.Color.dark_grey())
    
    if role_sep:
        for member in guild.members:
            if not member.bot and role_sep not in member.roles:
                try:
                    await member.add_roles(role_sep)
                except discord.Forbidden:
                    pass

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "SELECT discord_id, level FROM player_stats WHERE discord_id IS NOT NULL"
            cursor.execute(sql)
            joueurs = cursor.fetchall()
            
            for j in joueurs:
                member = guild.get_member(int(j['discord_id']))
                if not member:
                    continue
                
                lvl = j['level']
                if lvl < 5:
                    palier = 1
                else:
                    palier = (lvl // 5) * 5
                    
                nom_role_cible = f"Niveau {palier}"
                role_cible = await get_or_create_role(guild, nom_role_cible, discord.Color.teal())
                
                roles_a_retirer = [
                    r for r in member.roles 
                    if r.name.startswith("Niveau ") and r.name != nom_role_cible
                ]
                if roles_a_retirer:
                    await member.remove_roles(*roles_a_retirer)
                
                if role_cible and role_cible not in member.roles:
                    await member.add_roles(role_cible)
                    print(f"⭐ {member.display_name} a atteint le palier {nom_role_cible} !")
                    
    except Exception as e:
        print(f"Erreur lors de la mise à jour des rôles : {e}")
    finally:
        if 'conn' in locals() and conn.open:
            conn.close()

# --- SERVEUR WEB POUR GARDER LE BOT ACTIF ---
app = Flask('')

@app.route('/')
def home():
    return "Le bot est en ligne !"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

t = Thread(target=run_flask)
t.start()

bot.run(TOKEN)