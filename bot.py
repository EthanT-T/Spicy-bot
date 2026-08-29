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

NOM_ROLE_REPERE = "VIP"
NOM_SEPARATEUR = "─── Niveaux ───"

DB_HOST = os.environ.get('DB_HOST', 'mysql-spicy-anomaly.alwaysdata.net')
DB_USER = os.environ.get('DB_USER', 'spicy-anomaly_admin')
DB_PASS = os.environ.get('DB_PASS', 'p7$8FhKDQ@3xgxMb')
DB_NAME = os.environ.get('DB_NAME', 'spicy-anomaly_stats')

intents = discord.Intents.default()
intents.members = True

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

def is_valid_url(url):
    """Vérifie si une URL est correctement formée"""
    regex = re.compile(
        r'^(?:http|ftp)s?://' # http:// ou https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' # domaine
        r'localhost|' # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ou IP
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
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
        await bot.change_presence(activity=discord.Game(name="SCP: Secret Laboratory"))
    except Exception:
        await bot.change_presence(activity=discord.Game(name="🔴 Serveur Hors Ligne"))
    finally:
        if 'conn' in locals() and conn.open:
            conn.close()

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

                # Nettoyage et validation de l'URL de l'image
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
                    else:
                        print(f"⚠️ URL d'image invalide ignorée en BDD pour l'événement {event_db_id}: '{raw_image_url}'")

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
                        # On n'applique l'image à l'embed que si elle est valide
                        if valid_image_url:
                            embed.set_image(url=valid_image_url)
                            
                        embed.set_footer(text=f"Organisé par {ev['staff_implique']}")
                        await salon.send("@everyone", embed=embed)

                    cursor.execute("UPDATE server_events SET discord_event_id = %s WHERE id = %s", (str(discord_event.id), event_db_id))
                    conn.commit()
                    print(f"🎉 Événement {ev['titre']} créé avec succès sur Discord !")

                except Exception as ex:
                    print(f"Erreur création événement Discord : {ex}")
                    cursor.execute("UPDATE server_events SET discord_event_id = NULL WHERE id = %s", (event_db_id,))
                    conn.commit()

    except Exception as e:
        print(f"Erreur DB check events: {e}")
    finally:
        if 'conn' in locals() and conn.open:
            conn.close()

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