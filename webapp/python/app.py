import MySQLdb.cursors
import flask
import functools
import hashlib
import math
import os
import pathlib
import random
import string
import tempfile
import time
import logging
import gzip
import shutil
from functools import partial
from sqlalchemy import create_engine
import newrelic.agent


logging.basicConfig(filename='/tmp/isubata.log')
newrelic.agent.initialize('/home/isucon/isubata/webapp/python/newrelic.ini')

static_folder = pathlib.Path(__file__).resolve().parent.parent / 'public'
icons_folder = static_folder / 'icons'

app = flask.Flask(__name__)
app.secret_key = 'tonymoris'
avatar_max_size = 1 * 1024 * 1024

if not os.path.exists(str(icons_folder)):
    os.makedirs(str(icons_folder))

config = {
    'db_host': os.environ.get('ISUBATA_DB_HOST', 'localhost'),
    'db_port': int(os.environ.get('ISUBATA_DB_PORT', '3306')),
    'db_user': os.environ.get('ISUBATA_DB_USER', 'root'),
    'db_password': os.environ.get('ISUBATA_DB_PASSWORD', ''),
}


SCHEME = 'mysql://{user}:{passwd}@{host}/{db}'.format(
    user=os.environ.get('ISUBATA_DB_USER', 'root'),
    passwd=os.environ.get('ISUBATA_DB_PASSWORD', ''),
    host=os.environ.get('ISUBATA_DB_HOST', 'localhost'),
    db='isubata'
)
DBCONF = {'charset': 'utf8mb4', 'autocommit': True}

dbengine = create_engine(SCHEME, connect_args=DBCONF)


def dbh():
    if hasattr(flask.g, 'db'):
        return flask.g.db

    conn = dbengine.raw_connection()
    conn.cursor = partial(conn.cursor, MySQLdb.cursors.DictCursor)
    flask.g.db = conn

    cur = flask.g.db.cursor()
    cur.execute("SET SESSION sql_mode='TRADITIONAL,NO_AUTO_VALUE_ON_ZERO,ONLY_FULL_GROUP_BY'")
    return flask.g.db


@app.teardown_appcontext
def teardown(error):
    if hasattr(flask.g, "db"):
        flask.g.db.close()


@app.route('/initialize')
def get_initialize():
    cur = dbh().cursor()
    cur.execute("DELETE FROM user WHERE id > 1000")
    cur.execute("DELETE FROM image WHERE id > 1001")
    cur.execute("DELETE FROM channel WHERE id > 10")
    cur.execute("DELETE FROM message WHERE id > 10000")
    cur.execute("DELETE FROM haveread")
    cur.close()
    return ('', 204)


def db_get_user(cur, user_id):
    cur.execute("SELECT * FROM user WHERE id = %s", (user_id,))
    return cur.fetchone()


def db_add_message(cur, channel_id, user_id, content):
    cur.execute("INSERT INTO message (channel_id, user_id, content, created_at) VALUES (%s, %s, %s, NOW())",
                (channel_id, user_id, content))


def login_required(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not "user_id" in flask.session:
            return flask.redirect('/login', 303)
        flask.request.user_id = user_id = flask.session['user_id']
        user = db_get_user(dbh().cursor(), user_id)
        if not user:
            flask.session.pop('user_id', None)
            return flask.redirect('/login', 303)
        flask.request.user = user
        return func(*args, **kwargs)
    return wrapper


def random_string(n):
    return ''.join([random.choice(string.ascii_letters + string.digits) for i in range(n)])


def register(cur, user, password):
    salt = random_string(20)
    pass_digest = hashlib.sha1((salt + password).encode('utf-8')).hexdigest()
    try:
        cur.execute(
            "INSERT INTO user (name, salt, password, display_name, avatar_icon, created_at)"
            " VALUES (%s, %s, %s, %s, %s, NOW())",
            (user, salt, pass_digest, user, "default.png"))
        cur.execute("SELECT LAST_INSERT_ID() AS last_insert_id")
        return cur.fetchone()['last_insert_id']
    except MySQLdb.IntegrityError:
        flask.abort(409)


@app.route('/')
def get_index():
    if "user_id" in flask.session:
        return flask.redirect('/channel/1', 303)
    return flask.render_template('index.html')


def get_channel_list_info(focus_channel_id=None):
    cur = dbh().cursor()
    cur.execute("SELECT * FROM channel ORDER BY id")
    channels = cur.fetchall()
    description = ""

    for c in channels:
        if c['id'] == focus_channel_id:
            description = c['description']
            break

    return channels, description


@app.route('/channel/<int:channel_id>')
@login_required
def get_channel(channel_id):
    channels, description = get_channel_list_info(channel_id)
    return flask.render_template('channel.html',
                                 channels=channels, channel_id=channel_id, description=description)


@app.route('/register')
def get_register():
    return flask.render_template('register.html')


@app.route('/register', methods=['POST'])
def post_register():
    name = flask.request.form['name']
    pw = flask.request.form['password']
    if not name or not pw:
        flask.abort(400)
    user_id = register(dbh().cursor(), name, pw)
    flask.session['user_id'] = user_id
    return flask.redirect('/', 303)


@app.route('/login')
def get_login():
    return flask.render_template('login.html')


@app.route('/login', methods=['POST'])
def post_login():
    name = flask.request.form['name']
    cur = dbh().cursor()
    cur.execute("SELECT * FROM user WHERE name = %s", (name,))
    row = cur.fetchone()
    if not row or row['password'] != hashlib.sha1(
            (row['salt'] + flask.request.form['password']).encode('utf-8')).hexdigest():
        flask.abort(403)
    flask.session['user_id'] = row['id']
    return flask.redirect('/', 303)


@app.route('/logout')
def get_logout():
    flask.session.pop('user_id', None)
    return flask.redirect('/', 303)


@app.route('/message', methods=['POST'])
def post_message():
    user_id = flask.session['user_id']
    user = db_get_user(dbh().cursor(), user_id)
    message = flask.request.form['message']
    channel_id = int(flask.request.form['channel_id'])
    if not user or not message or not channel_id:
        flask.abort(403)
    db_add_message(dbh().cursor(), channel_id, user_id, message)
    return ('', 204)


@app.route('/message')
def get_message():
    user_id = flask.session.get('user_id')
    if not user_id:
        flask.abort(403)

    channel_id = int(flask.request.args.get('channel_id'))
    last_message_id = int(flask.request.args.get('last_message_id'))
    cur = dbh().cursor()
    cur.execute('SELECT M.id, M.created_at, M.content, U.name, U.display_name, U.avatar_icon FROM message M, user U'
                    ' WHERE M.id > %s AND M.channel_id = %s AND U.id = M.user_id ORDER BY M.id DESC LIMIT 100',
                (last_message_id, channel_id))
    response = list({'id': row['id'], 'user': {'name': row['name'], 'display_name': row['display_name'], 'avatar_icon': row['avatar_icon']},
                     'date': row['created_at'].strftime("%Y/%m/%d %H:%M:%S"),
                     'content': row['content']} for row in cur.fetchall())
    response.reverse()

    max_message_id = max(r['id'] for r in response) if response else 0
    cur.execute('INSERT INTO haveread (user_id, channel_id, message_id, updated_at, created_at)'
                ' VALUES (%s, %s, %s, NOW(), NOW())'
                ' ON DUPLICATE KEY UPDATE message_id = %s, updated_at = NOW()',
                (user_id, channel_id, max_message_id, max_message_id))

    return flask.jsonify(response)


@app.route('/fetch')
def fetch_unread():
    user_id = flask.session.get('user_id')
    if not user_id:
        flask.abort(403)

#    time.sleep(1.0)

    cur = dbh().cursor()
    cur.execute('SELECT id FROM channel')
    udict = {}
    for r in cur.fetchall():
      udict[r['id']] = 0

    cur.execute('SELECT channel_id, COUNT(id) as cnt FROM message GROUP BY channel_id')
    for r in cur.fetchall():
      udict[r['channel_id']] = int(r['cnt'])

    cur.execute('SELECT C.id as channel_id, ('
                '  SELECT COUNT(id) as cnt FROM message WHERE channel_id = C.id AND R.message_id < id'
                ') AS cnt FROM channel C, haveread R'
                ' WHERE C.id = R.channel_id AND R.user_id = %s', (user_id,))
    ucounts = cur.fetchall()
    for r in ucounts:
      if r['channel_id'] in udict:
        udict[r['channel_id']] = int(r['cnt'])

    return flask.jsonify(list({'channel_id': cid, 'unread': unread} for cid, unread in udict.items()))


@app.route('/history/<int:channel_id>')
@login_required
def get_history(channel_id):
    page = flask.request.args.get('page')
    if not page:
        page = '1'
    if not page.isnumeric():
        flask.abort(400)
    page = int(page)

    N = 20
    cur = dbh().cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM message WHERE channel_id = %s", (channel_id,))
    cnt = int(cur.fetchone()['cnt'])
    max_page = math.ceil(cnt / N)
    if not max_page:
        max_page = 1

    if not 1 <= page <= max_page:
        flask.abort(400)

    cur.execute("SELECT * FROM message WHERE channel_id = %s ORDER BY id DESC LIMIT %s OFFSET %s",
                (channel_id, N, (page - 1) * N))
    rows = cur.fetchall()
    messages = []
    for row in rows:
        r = {}
        r['id'] = row['id']
        cur.execute("SELECT name, display_name, avatar_icon FROM user WHERE id = %s", (row['user_id'],))
        r['user'] = cur.fetchone()
        r['date'] = row['created_at'].strftime("%Y/%m/%d %H:%M:%S")
        r['content'] = row['content']
        messages.append(r)
    messages.reverse()

    channels, description = get_channel_list_info(channel_id)
    return flask.render_template('history.html',
                                 channels=channels, channel_id=channel_id,
                                 messages=messages, max_page=max_page, page=page)


@app.route('/profile/<user_name>')
@login_required
def get_profile(user_name):
    channels, _ = get_channel_list_info()

    cur = dbh().cursor()
    cur.execute("SELECT * FROM user WHERE name = %s", (user_name,))
    user = cur.fetchone()

    if not user:
        flask.abort(404)

    self_profile = flask.request.user['id'] == user['id']
    return flask.render_template('profile.html', channels=channels, user=user, self_profile=self_profile)


@app.route('/add_channel')
@login_required
def get_add_channel():
    channels, _ = get_channel_list_info()
    return flask.render_template('add_channel.html', channels=channels)


@app.route('/add_channel', methods=['POST'])
@login_required
def post_add_channel():
    name = flask.request.form['name']
    description = flask.request.form['description']
    if not name or not description:
        flask.abort(400)
    cur = dbh().cursor()
    cur.execute("INSERT INTO channel (name, description, updated_at, created_at) VALUES (%s, %s, NOW(), NOW())",
                (name, description))
    channel_id = cur.lastrowid
    return flask.redirect('/channel/' + str(channel_id), 303)


@app.route('/profile', methods=['POST'])
@login_required
def post_profile():
    user_id = flask.session.get('user_id')
    if not user_id:
        flask.abort(403)

    cur = dbh().cursor()
    user = db_get_user(cur, user_id)
    if not user:
        flask.abort(403)

    display_name = flask.request.form.get('display_name')
    avatar_name = None

    if 'avatar_icon' in flask.request.files:
        file = flask.request.files['avatar_icon']
        if file.filename:
            ext = os.path.splitext(file.filename)[1] if '.' in file.filename else ''
            if ext not in ('.jpg', '.jpeg', '.png', '.gif'):
                flask.abort(400)

            with tempfile.TemporaryFile() as f:
                file.save(f)
                f.flush()

                if avatar_max_size < f.tell():
                    flask.abort(400)

                f.seek(0)
                file.seek(0)
                data = f.read()
                digest = hashlib.sha1(data).hexdigest()

                avatar_name = digest + ext

            fname = '%s/%s' % (str(icons_folder), avatar_name)
            file.save(fname)

            file.seek(0)
            with gzip.open('%s.gz' % fname, 'wb') as gz:
                shutil.copyfileobj(file, gz)

    if avatar_name and display_name:
        cur.execute("UPDATE user SET display_name = %s, avatar_icon = %s WHERE id = %s", (display_name, avatar_name, user_id))
    elif avatar_name:
        cur.execute("UPDATE user SET avatar_icon = %s WHERE id = %s", (avatar_name, user_id))
    elif display_name:
        cur.execute("UPDATE user SET display_name = %s WHERE id = %s", (display_name, user_id))

    return flask.redirect('/', 303)


if __name__ == "__main__":
    app.run(port=8080, debug=True, threaded=True)
