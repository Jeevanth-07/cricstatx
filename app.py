from flask import Flask, render_template, request, redirect, session
import sqlite3, pdfplumber, re

app = Flask(__name__)
app.secret_key = "cricstatx"

def db():
    return sqlite3.connect("database.db")

def parse_pdf(file):
    batsmen = {}
    bowlers = {}

    with pdfplumber.open(file) as pdf:
        text = "\n".join(p.extract_text() for p in pdf.pages)

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    for line in lines:
        m = re.match(r'^([A-Za-z]+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)', line)
        if m:
            batsmen[m.group(1)] = (int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
            continue

        m = re.match(r'^([A-Za-z]+)\s+([\d.]+)\s+\d+\s+(\d+)\s+(\d+)\s+([\d.]+)', line)
        if m:
            overs = float(m.group(2))
            runs = int(m.group(3))
            wickets = int(m.group(4))
            balls = int(overs * 6)
            bowlers[m.group(1)] = (wickets, runs, balls)

    return batsmen, bowlers

def upsert(cur, name, bat_runs=0, bat_balls=0, wickets=0,
           bowl_runs=0, bowl_balls=0, fours=0, sixes=0, out=0):
    cur.execute("SELECT hs FROM players WHERE name=?", (name,))
    r = cur.fetchone()

    if r:
        new_hs = max(r[0], bat_runs)
        cur.execute("""
            UPDATE players SET
            runs = runs + ?,
            balls = balls + ?,
            wickets = wickets + ?,
            bowl_runs = bowl_runs + ?,
            bowl_balls = bowl_balls + ?,
            outs = outs + ?,
            fours = fours + ?,
            sixes = sixes + ?,
            hs = ?
            WHERE name = ?
        """,(bat_runs,bat_balls,wickets,bowl_runs,bowl_balls,out,fours,sixes,new_hs,name))
    else:
        cur.execute("""
            INSERT INTO players(name,matches,runs,balls,wickets,overs,outs,bowl_runs,bowl_balls,fours,sixes,hs)
            VALUES(?,0,?,?,?,?,?,?,?,?,?,?)
        """,(name,bat_runs,bat_balls,wickets,0,out,bowl_runs,bowl_balls,fours,sixes,bat_runs))

@app.route("/", methods=["GET","POST"])
def index():
    con = db()
    cur = con.cursor()
    q = request.form.get("q")

    if q:
        cur.execute("SELECT * FROM players WHERE name LIKE ?",('%'+q+'%',))
    else:
        cur.execute("SELECT * FROM players")

    data = cur.fetchall()
    con.close()

    def safe_int(v):
        try:
            return int(v)
        except:
            return 0

    batting = sorted(data, key=lambda x: safe_int(x[2]), reverse=True)
    bowling = sorted(data, key=lambda x: safe_int(x[4]), reverse=True)

    return render_template("index.html", batting=batting, bowling=bowling)


@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST" and request.form["u"]=="admin" and request.form["p"]=="admin123":
        session["admin"] = True
        return redirect("/admin")
    return render_template("login.html")

@app.route("/admin", methods=["GET","POST"])
def admin():
    if not session.get("admin"):
        return redirect("/login")

    con = db()
    cur = con.cursor()

    # PDF Upload
    if request.method=="POST" and request.form.get("action")=="upload":
        bats,bowl=parse_pdf(request.files["file"])

        for n,(r,b,f4,f6) in bats.items():
            upsert(cur,n,bat_runs=r,bat_balls=b,fours=f4,sixes=f6,out=1)
            cur.execute("UPDATE players SET matches=matches+1 WHERE name=?",(n,))
        for n,(w,br,bb) in bowl.items():
            upsert(cur,n,wickets=w,bowl_runs=br,bowl_balls=bb)
        con.commit()

    # Reset DB
    if request.method=="POST" and request.form.get("action")=="reset":
        cur.execute("DELETE FROM players")
        con.commit()

    # Manual Edit (SAFE)
    if request.method=="POST" and request.form.get("action")=="edit":
        old = request.form["old"]
        new = request.form["name"].strip()

        # If name is changed, check uniqueness
        if new != old:
            cur.execute("SELECT 1 FROM players WHERE name=?", (new,))
            if cur.fetchone():
                con.close()
                return "❌ Player name already exists. Choose a different name."

        cur.execute("""
            UPDATE players SET
            name=?, runs=?, balls=?, wickets=?, bowl_runs=?, bowl_balls=?, 
            fours=?, sixes=?, hs=?
            WHERE name=?
        """,(
            new,
            request.form["runs"],
            request.form["balls"],
            request.form["wickets"],
            request.form["bowl_runs"],
            request.form["bowl_balls"],
            request.form["fours"],
            request.form["sixes"],
            request.form["hs"],
            old
        ))
        con.commit()

    # Dashboard info
    cur.execute("SELECT * FROM players")
    players_list=cur.fetchall()

    cur.execute("SELECT COUNT(*) FROM players")
    players_count=cur.fetchone()[0]

    cur.execute("SELECT SUM(matches) FROM players")
    matches=cur.fetchone()[0] or 0

    con.close()
    return render_template("admin.html",
        players_list=players_list,
        count=players_count,
        matches=matches
    )


@app.route("/logout")

def logout():
    session.clear()
    return redirect("/")

app.run(host="0.0.0.0", port=5000, debug=True)
