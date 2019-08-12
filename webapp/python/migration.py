import os
import gzip
import MySQLdb.cursors

TARGET = '/home/isucon/isubata/webapp/public/icons'

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


db = MySQLdb.connect(**DBCONF)
csr = db.cursor()


csr.execute('SELECT id FROM image')
for image in csr.fetchall():
  iid = image['id']
  csr.execute('SELECT name, data FROM image WHERE id = %s', (iid,))

  row = csr.fetchone()

  fname = '%s/%s' % (TARGET, row['name'])
  with open(fname, 'wb') as f:
    f.write(row['data'])

  with gzip.open(fname + '.gz', 'wb') as gz:
    gz.write(row['data'])

  print(fname)

