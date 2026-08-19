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
# CONFIGURATION
# ==========================================

TOKEN = os.environ.get('DISCORD_TOKEN')
ID_SERVEUR_DISCORD = 1392952674604814487  # ID de ton serveur Discord
ID_SALON_ANNONCES = 1234567890            # ⚠️ REMPLACE PAR L'ID DU SALON D'ANNONCE
NOM_ROLE_REPERE = "VIP"                   # Nom exact du rôle sous lequel placer les niveaux
NOM_SEPARATEUR = "─── Niveaux ───"         # Nom du rôle séparateur

# Configuration MySQL
DB_HOST = 'mysql-spicy-anomaly.alwaysdata.net'
DB_USER = 'spicy-anomaly_admin'
DB_PASS = 'p7$8FhKDQ@3xgxMb'
DB_NAME = 'spicy-anomaly_stats'

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
        host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME, cursorclass=pymysql.cursors.DictCursor
    )

async def get_or_create_role(guild, role_name, color=discord.Color.default()):
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        try:
            role = await guild.create_role(name=role_name, color=color, reason="Création auto")
            role_repere = discord.utils.get(guild.roles, name=NOM_ROLE_REPERE)
            if role_repere and guild.me.top_role.position > role_repere.position:
                await role.edit(position=max(1, role_repere.position - 1))
        except Exception:
            pass
    return role

@bot.event
async def on_ready():
    print(f'✅ Bot connecté en tant que {bot.user} !')
    if not check_levels_and_roles.is_running():
        check_levels_and_roles.start()
    if not check_new_events.is_running():
        check_new_events.start()

@bot.event
async def on_member_join(member):
    if member.bot: return
    role_sep = await get_or_create_role(member.guild, NOM_SEPARATEUR, discord.Color.dark_grey())
    if role_sep and role_sep not in member.roles:
        try: await member.add_roles(role_sep)
        except: pass

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
            # On cherche les événements pas encore postés sur Discord
            cursor.execute("SELECT * FROM server_events WHERE discord_event_id IS NULL")
            new_events = cursor.fetchall()

            for ev in new_events:
                # 1. Préparation de la date (Heure de Paris)
                tz = pytz.timezone('Europe/Paris')
                try:
                    # Le HTML envoie un format "YYYY-MM-DDTHH:MM"
                    start_time = datetime.strptime(ev['date_event'], '%Y-%m-%dT%H:%M')
                    start_time = tz.localize(start_time)
                except:
                    # Fallback au cas où le format change
                    start_time = datetime.now(tz) + timedelta(minutes=10)

                # Si l'heure est dans le passé, on la décale pour éviter le crash Discord
                if start_time < datetime.now(tz):
                    start_time = datetime.now(tz) + timedelta(minutes=5)
                
                end_time = start_time + timedelta(hours=2) # Par défaut, dure 2 heures

                # 2. Récupération de l'image en bytes
                image_bytes = None
                if ev['image_url']:
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(ev['image_url']) as resp:
                                if resp.status == 200:
                                    image_bytes = await resp.read()
                    except:
                        pass # Ignore l'image si le lien est mort

                # 3. Création de l'événement natif Discord
                try:
                    discord_event = await guild.create_scheduled_event(
                        name=f"🎉 {ev['titre']}",
                        description=f"{ev['description']}\n\n👥 Supervisé par : **{ev['staff_implique']}**",
                        start_time=start_time,
                        end_time=end_time,
                        entity_type=discord.EntityType.external,
                        location="Serveur Spicy Anomaly",
                        privacy_level=discord.PrivacyLevel.guild_only,
                        image=image_bytes
                    )

                    # 4. Message d'annonce dans le salon avec le lien cliquable
                    salon = guild.get_channel(ID_SALON_ANNONCES)
                    if salon:
                        embed = discord.Embed(
                            title=f"🚨 NOUVEL ÉVÉNEMENT : {ev['titre']}",
                            description=f"{ev['description']}\n\n👉 **[Clique ici pour t'inscrire et recevoir une alerte !]({discord_event.url})**",
                            color=0xe63946
                        )
                        if ev['image_url']:
                            embed.set_image(url=ev['image_url'])
                        embed.set_footer(text=f"Organisé par {ev['staff_implique']}")
                        await salon.send("@everyone", embed=embed)

                    # 5. Marquer l'événement comme posté en BDD
                    cursor.execute("UPDATE server_events SET discord_event_id = %s WHERE id = %s", (discord_event.id, ev['id']))
                    conn.commit()
                    print(f"🎉 Événement {ev['titre']} créé avec succès sur Discord !")

                except Exception as ex:
                    print(f"Erreur création événement Discord : {ex}")
    except Exception as e:
        print(f"Erreur DB check events: {e}")
    finally:
        if 'conn' in locals() and conn.open:
            conn.close()

# Boucle d'actualisation des rôles (raccourcie pour la lecture)
@tasks.loop(minutes=5)
async def check_levels_and_roles():
    pass # GARDE TON CODE PRÉCÉDENT ICI POUR LES NIVEAUX

@bot.tree.command(name="lier", description="Lie ton compte Discord à ton SteamID64")
@app_commands.describe(steamid="Ton SteamID64 (ex: 7656119...)")
async def lier_compte(interaction: discord.Interaction, steamid: str):
    pass # GARDE TON CODE PRÉCÉDENT ICI

@bot.tree.command(name="stats", description="Affiche tes statistiques et ton niveau")
async def voir_stats(interaction: discord.Interaction):
    pass # GARDE TON CODE PRÉCÉDENT ICI

app = Flask('')
@app.route('/')
def home():
    return "Le bot est en ligne !"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

t = Thread(target=run_flask)
t.start()
bot.run(TOKEN)