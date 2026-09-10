import os
import asyncio
import random
import sqlite3
import discord
from discord.ext import commands

# ============================================
# CONFIGURATION
# ============================================
TOKEN = os.environ.get("DISCORD_TOKEN")  # le token sera mis dans les variables d'environnement (jamais dans le code)
SETUP_CODE = os.environ.get("SETUP_CODE", "change-moi")  # code secret pour devenir admin, à définir toi-même

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ============================================
# BASE DE DONNEES (fichier local, persiste entre redémarrages)
# ============================================
db = sqlite3.connect("contacts.db")
db.execute("""
CREATE TABLE IF NOT EXISTS contacts (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    groupe TEXT DEFAULT 'A'
)
""")
db.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
db.commit()


def is_admin(ctx):
    row = db.execute("SELECT 1 FROM admins WHERE user_id=?", (ctx.author.id,)).fetchone()
    return row is not None


# ============================================
# EVENEMENTS
# ============================================
@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user}")


# ============================================
# DEVENIR ADMIN (une seule fois, avec le code secret)
# ============================================
@bot.command()
async def devenir_admin(ctx, code: str):
    """Usage: !devenir_admin TON_CODE_SECRET"""
    if code != SETUP_CODE:
        await ctx.author.send("Code incorrect.")
        return
    db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (ctx.author.id,))
    db.commit()
    try:
        await ctx.message.delete()  # supprime le message contenant le code du canal
    except discord.Forbidden:
        pass
    await ctx.author.send("Tu es maintenant admin ✅")


# ============================================
# INSCRIPTION (privée — personne ne voit qui est inscrit)
# ============================================
@bot.command()
async def inscription(ctx):
    """L'utilisateur s'inscrit à la liste de diffusion."""
    existing = db.execute(
        "SELECT 1 FROM contacts WHERE user_id=?", (ctx.author.id,)
    ).fetchone()

    if existing:
        await ctx.author.send("Tu es déjà inscrit ✅")
        return

    db.execute(
        "INSERT INTO contacts (user_id, username, groupe) VALUES (?, ?, ?)",
        (ctx.author.id, str(ctx.author), "A"),
    )
    db.commit()

    try:
        await ctx.author.send("Inscription confirmée ✅ Tu recevras les messages en privé.")
    except discord.Forbidden:
        await ctx.send(
            f"{ctx.author.mention} inscription reçue, mais je ne peux pas t'envoyer de DM. "
            "Vérifie tes paramètres de confidentialité (autoriser les messages privés des membres du serveur)."
        )


@bot.command()
async def desinscription(ctx):
    """L'utilisateur se retire de la liste."""
    db.execute("DELETE FROM contacts WHERE user_id=?", (ctx.author.id,))
    db.commit()
    await ctx.author.send("Tu as été désinscrit.")


# ============================================
# ADMIN : voir la liste / changer un groupe
# ============================================
@bot.command()
async def stats(ctx):
    """Nombre d'inscrits par groupe (admin uniquement)."""
    if not is_admin(ctx):
        return
    rows = db.execute("SELECT groupe, COUNT(*) FROM contacts GROUP BY groupe").fetchall()
    total = db.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    texte = f"Total inscrits : {total}\n" + "\n".join(f"Groupe {g} : {n}" for g, n in rows)
    await ctx.send(texte)


@bot.command()
async def assigner(ctx, membre: discord.Member, groupe: str):
    """Change le groupe d'un inscrit. Usage: !assigner @user B"""
    if not is_admin(ctx):
        return
    db.execute("UPDATE contacts SET groupe=? WHERE user_id=?", (groupe, membre.id))
    db.commit()
    await ctx.send(f"{membre} affecté au groupe {groupe}")


# ============================================
# DIVISER UN GROUPE EN SOUS-GROUPES (admin uniquement)
# ============================================
@bot.command()
async def diviser(ctx, groupe: str, n: int):
    """
    Divise un groupe existant en n sous-groupes à peu près égaux, répartis au hasard.
    Usage: !diviser A 2   -> crée A1 et A2 à partir des inscrits du groupe A
    Usage: !diviser tous 3 -> divise TOUS les inscrits en 3 sous-groupes (peu importe leur groupe actuel)
    """
    if not is_admin(ctx):
        return

    if n < 2:
        await ctx.send("n doit être au moins 2.")
        return

    if groupe.lower() == "tous":
        rows = db.execute("SELECT user_id FROM contacts").fetchall()
    else:
        rows = db.execute("SELECT user_id FROM contacts WHERE groupe=?", (groupe,)).fetchall()

    if not rows:
        await ctx.send("Aucun inscrit trouvé pour ce groupe.")
        return

    user_ids = [r[0] for r in rows]
    random.shuffle(user_ids)

    prefixe = "G" if groupe.lower() == "tous" else groupe
    for i, user_id in enumerate(user_ids):
        sous_groupe = f"{prefixe}{(i % n) + 1}"
        db.execute("UPDATE contacts SET groupe=? WHERE user_id=?", (sous_groupe, user_id))
    db.commit()

    noms = ", ".join(f"{prefixe}{i + 1}" for i in range(n))
    await ctx.send(
        f"✅ {len(user_ids)} inscrits répartis en {n} sous-groupes : {noms}\n"
        f"Utilise !diffuser {prefixe}1 ton message, !diffuser {prefixe}2 ton message, etc."
    )


# ============================================
# DIFFUSION (admin uniquement)
# ============================================
@bot.command()
async def diffuser(ctx, groupe: str, *, message: str):
    """
    Envoie un message en DM à tous les inscrits d'un groupe.
    Usage: !diffuser A Votre message ici
    Usage: !diffuser tous Votre message ici   (envoie à tout le monde)
    """
    if not is_admin(ctx):
        return

    if groupe.lower() == "tous":
        users = db.execute("SELECT user_id FROM contacts").fetchall()
    else:
        users = db.execute("SELECT user_id FROM contacts WHERE groupe=?", (groupe,)).fetchall()

    if not users:
        await ctx.send("Aucun inscrit trouvé pour ce groupe.")
        return

    envoyes, echecs = 0, 0
    progress_msg = await ctx.send(f"Envoi en cours à {len(users)} personnes...")

    for (user_id,) in users:
        try:
            user = await bot.fetch_user(user_id)
            await user.send(message)
            envoyes += 1
        except (discord.Forbidden, discord.HTTPException):
            echecs += 1
        await asyncio.sleep(1.2)  # délai anti-spam obligatoire pour Discord

    await progress_msg.edit(content=f"✅ Terminé : {envoyes} envoyés, {echecs} échecs.")


# ============================================
# LANCEMENT
# ============================================
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("❌ DISCORD_TOKEN manquant. Ajoute-le dans les variables d'environnement.")
    bot.run(TOKEN)
