import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import secrets

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me-123')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///dart.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Tournament(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), default="Dart Turnier")
    mode = db.Column(db.String(10), default="501")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    points = db.Column(db.Integer, default=0)

class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    round_num = db.Column(db.Integer, nullable=False)
    player1_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    player2_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    p1_legs = db.Column(db.Integer, default=0)
    p2_legs = db.Column(db.Integer, default=0)
    finished = db.Column(db.Boolean, default=False)

class Invite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    used = db.Column(db.Boolean, default=False)
    is_group = db.Column(db.Boolean, default=False)

def generate_round_robin(players):
    n = len(players)
    if n % 2 != 0:
        players = players + [None]
        n += 1
    rounds = []
    fixed = players[0]
    rotating = players[1:]
    for r in range(n - 1):
        round_matches = []
        pair = [fixed] + rotating
        for i in range(n // 2):
            p1 = pair[i]
            p2 = pair[n - 1 - i]
            if p1 and p2:
                round_matches.append((p1, p2))
        rounds.append(round_matches)
        rotating = [rotating[-1]] + rotating[:-1]
    return rounds

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    tournament = Tournament.query.first()
    if not tournament:
        tournament = Tournament(name="Dart Turnier")
        db.session.add(tournament)
        db.session.commit()
    players = Player.query.filter_by(tournament_id=tournament.id).order_by(Player.points.desc()).all()
    matches = Match.query.filter_by(tournament_id=tournament.id).order_by(Match.round_num, Match.id).all()
    return render_template('index.html', user=user, tournament=tournament, players=players, matches=matches)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            username = request.form['username'].strip()
            password = request.form['password']
            if not username or not password:
                flash('Name und Passwort nötig')
                return redirect(url_for('register'))
            if User.query.filter_by(username=username).first():
                flash('Name bereits vergeben')
                return redirect(url_for('register'))
            is_first = User.query.count() == 0
            user = User(
                username=username,
                password_hash=generate_password_hash(password),
                is_admin=is_first
            )
            db.session.add(user)
            db.session.commit()
            session['user_id'] = user.id
            return redirect(url_for('index'))
        except Exception:
            db.session.rollback()
            flash('Fehler bei der Registrierung')
            return redirect(url_for('register'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session['user_id'] = user.id
            return redirect(url_for('index'))
        flash('Falsche Anmeldedaten')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/add_player', methods=['POST'])
def add_player():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    name = request.form['name'].strip()
    tournament = Tournament.query.first()
    if name and tournament:
        p = Player(name=name, tournament_id=tournament.id)
        db.session.add(p)
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/generate_schedule')
def generate_schedule():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if not user.is_admin:
        flash('Nur Admin')
        return redirect(url_for('index'))
    tournament = Tournament.query.first()
    players = Player.query.filter_by(tournament_id=tournament.id).all()
    if len(players) < 2:
        flash('Mindestens 2 Spieler nötig')
        return redirect(url_for('index'))
    Match.query.filter_by(tournament_id=tournament.id).delete()
    rounds = generate_round_robin(players)
    for r_idx, round_matches in enumerate(rounds, 1):
        for p1, p2 in round_matches:
            m = Match(tournament_id=tournament.id, round_num=r_idx, player1_id=p1.id, player2_id=p2.id)
            db.session.add(m)
    db.session.commit()
    flash(f'Spielplan mit {len(rounds)} Runden erstellt')
    return redirect(url_for('index'))

@app.route('/update_match/<int:match_id>', methods=['POST'])
def update_match(match_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    match = Match.query.get_or_404(match_id)
    p1_legs = int(request.form.get('p1_legs', 0))
    p2_legs = int(request.form.get('p2_legs', 0))
    if p1_legs + p2_legs == 0:
        return redirect(url_for('index'))
    if match.finished:
        p1 = Player.query.get(match.player1_id)
        p2 = Player.query.get(match.player2_id)
        p1.points -= (match.p1_legs - match.p2_legs)
        p2.points -= (match.p2_legs - match.p1_legs)
    match.p1_legs = p1_legs
    match.p2_legs = p2_legs
    match.finished = True
    p1 = Player.query.get(match.player1_id)
    p2 = Player.query.get(match.player2_id)
    p1.points += (p1_legs - p2_legs)
    p2.points += (p2_legs - p1_legs)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/create_invite')
def create_invite():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if not user.is_admin:
        return redirect(url_for('index'))
    is_group = request.args.get('group') == '1'
    code = secrets.token_urlsafe(8)
    inv = Invite(code=code, created_by=user.id, is_group=is_group)
    db.session.add(inv)
    db.session.commit()
    link = url_for('register', _external=True) + f'?code={code}'
    flash(f'Einladungslink: {link}')
    return redirect(url_for('index'))

@app.route('/set_mode', methods=['POST'])
def set_mode():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    tournament = Tournament.query.first()
    tournament.mode = request.form.get('mode', '501')
    db.session.commit()
    return redirect(url_for('index'))

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))