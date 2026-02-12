from flask import Flask, render_template, request, redirect, session
import sqlite3, pdfplumber, re

app = Flask(__name__)
app.secret_key = "cricstatx"

def db():
    return sqlite3.connect("database.db")

# ================= PDF PARSER =================

def parse_pdf(file):
    batsmen = {}
    bowlers = {}

    with pdfplumber.open(file) as pdf:
        text = "\n".join(p.extract_text() for p in pdf.pages)

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    for line in lines:
        m = re.match(r'^([A-Za-z]+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)', line)
        if m:
            batsmen[m.group(1)] = (
                int(m.group(2)),
                int(m.group(3)),
                int(m.group(4)),
                int(m.group(5))
            )
            continue

        m = re.match(r'^([A-Za-z]+)\s+([\d.]+)\s+\d+\s+(\d+)\s+(\d+)\s+([\d.]+)', line)
        if m:
            overs = float(m.group(2))
            runs = int(m.group(3))
            wickets = int(m.group(4))
            balls = int(overs * 6)
            bowlers[m.group(1)] = (wickets, runs, balls)

    return batsmen, bowlers

# ================= UPSERT =================

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

# ================= INDEX =================

@app.route("/", methods=["GET"])
def index():
    con = db()
    cur = con.cursor()

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

# ================= LOGIN =================

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST" and request.form["u"]=="admin" and request.form["p"]=="admin123":
        session["admin"] = True
        return redirect("/admin")
    return render_template("login.html")

# ================= ADMIN =================

@app.route("/admin", methods=["GET","POST"])
def admin():
    if not session.get("admin"):
        return redirect("/login")

    con = db()
    cur = con.cursor()

    # ========= UPLOAD =========
    if request.method=="POST" and request.form.get("action")=="upload":

        files = request.files.getlist("files")

        for file in files:
            if file and file.filename != "":
                bats, bowl = parse_pdf(file)

                for n,(r,b,f4,f6) in bats.items():
                    upsert(cur,n,bat_runs=r,bat_balls=b,fours=f4,sixes=f6,out=1)
                    cur.execute("UPDATE players SET matches=matches+1 WHERE name=?",(n,))

                for n,(w,br,bb) in bowl.items():
                    upsert(cur,n,wickets=w,bowl_runs=br,bowl_balls=bb)

        con.commit()

    # ========= RESET =========
    if request.method=="POST" and request.form.get("action")=="reset":
        cur.execute("DELETE FROM players")
        con.commit()

    # ========= EDIT PLAYER =========
    if request.method=="POST" and request.form.get("action")=="edit":

        old = request.form["old"]
        new = request.form["name"].strip()

        def safe_int(val):
            try:
                return int(val)
            except:
                return 0

        cur.execute("""
            UPDATE players SET
            name=?,
            runs=?,
            balls=?,
            wickets=?,
            bowl_runs=?,
            bowl_balls=?,
            fours=?,
            sixes=?,
            hs=?
            WHERE name=?
        """,(
            new,
            safe_int(request.form.get("runs")),
            safe_int(request.form.get("balls")),
            safe_int(request.form.get("wickets")),
            safe_int(request.form.get("bowl_runs")),
            safe_int(request.form.get("bowl_balls")),
            safe_int(request.form.get("fours")),
            safe_int(request.form.get("sixes")),
            safe_int(request.form.get("hs")),
            old
        ))

        con.commit()

    # ========= MERGE =========
    if request.method=="POST" and request.form.get("action")=="merge":

        source = request.form["source"]
        target = request.form["target"]

        if source != target:

            cur.execute("SELECT * FROM players WHERE name=?", (source,))
            s = cur.fetchone()

            cur.execute("SELECT * FROM players WHERE name=?", (target,))
            t = cur.fetchone()

            if s and t:
                new_hs = max(s[11], t[11])

                cur.execute("""
                    UPDATE players SET
                    matches = matches + ?,
                    runs = runs + ?,
                    balls = balls + ?,
                    wickets = wickets + ?,
                    outs = outs + ?,
                    bowl_runs = bowl_runs + ?,
                    bowl_balls = bowl_balls + ?,
                    fours = fours + ?,
                    sixes = sixes + ?,
                    hs = ?
                    WHERE name = ?
                """,(
                    s[1], s[2], s[3], s[4], s[6],
                    s[7], s[8], s[9], s[10],
                    new_hs,
                    target
                ))

                cur.execute("DELETE FROM players WHERE name=?", (source,))
                con.commit()

    # ========= LOAD DATA =========
    cur.execute("SELECT * FROM players")
    players_list = cur.fetchall()

    cur.execute("SELECT COUNT(*) FROM players")
    players_count = cur.fetchone()[0]

    cur.execute("SELECT SUM(matches) FROM players")
    matches = cur.fetchone()[0] or 0

    con.close()

    return render_template("admin.html",
        players_list=players_list,
        count=players_count,
        matches=matches
    )

# ================= DELETE =================

@app.route("/delete_player", methods=["POST"])
def delete_player():
    if not session.get("admin"):
        return redirect("/login")

    con = db()
    cur = con.cursor()
    cur.execute("DELETE FROM players WHERE name=?", (request.form["name"],))
    con.commit()
    con.close()
    return redirect("/admin")

# ================= LOGOUT =================

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
