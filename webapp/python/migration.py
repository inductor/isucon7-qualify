import os
import gzip
import MySQLdb.cursors

TARGET = '/home/isucon/isubata/webapp/public/icons'

PREFIX = {
    '2': '%s/02' % TARGET,
    '3': '%s/03' % TARGET
}


DBCONF = {
    'host': os.environ.get('ISUBATA_DB_HOST', 'localhost'),
    'port': int(os.environ.get('ISUBATA_DB_PORT', '3306')),
    'user': os.environ.get('ISUBATA_DB_USER', 'isucon'),
    'password': os.environ.get('ISUBATA_DB_PASSWORD', 'isucon'),
    'db': 'isubata',
    'charset': 'utf8mb4',
    'cursorclass': MySQLdb.cursors.DictCursor,
    'autocommit': True,
}


if not os.path.exists(PREFIX['2']):
    os.makedirs(PREFIX['2'])

if not os.path.exists(PREFIX['3']):
    os.makedirs(PREFIX['3'])

db = MySQLdb.connect(**DBCONF)
csr = db.cursor()


csr.execute('SELECT id FROM image')
for image in csr.fetchall():
    iid = image['id']
    csr.execute('SELECT name, data FROM image WHERE id = %s', (iid,))

    row = csr.fetchone()
    path = ''
    prefix = ''
    if iid % 2 == 0:
        path = PREFIX['2']
        prefix = '02/'
    else:
        path = PREFIX['3']
        prefix = '03/'

    fname = '%s/%s' % (path, row['name'])
    with open(fname, 'wb') as f:
        f.write(row['data'])

    with gzip.open(fname + '.gz', 'wb') as gz:
        gz.write(row['data'])

    csr.execute('UPDATE user SET icon = %s WHERE avatar_icon = %s', (prefix + row['name'], row['name']))
    print(fname)
