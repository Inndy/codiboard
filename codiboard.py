#!/usr/bin/env python3
from bottle import *
import psycopg2
import psycopg2.extras

import base64
import functools
import json
import re

app = Bottle()
app.config.load_config('config.ini')

docker_network_name = app.config.get('postgre.docker_network')

if docker_network_name:
    raw_cfg = subprocess.check_output(['docker', 'network', 'inspect', docker_network_name])
    for network in json.loads(raw_cfg):
        for cfg in network['Containers'].values():
            if cfg['Name'] == app.config.get('postgre.host'):
                app.config['postgre.host'] = cfg['IPv4Address'].split('/')[0]
                print('[*] Use postgre.host from network: %r' % network)

db = psycopg2.connect(host=app.config['postgre.host'], dbname=app.config['postgre.db'], user=app.config['postgre.user'], password=app.config['postgre.password'])

BaseTemplate.defaults['to_longid'] = lambda uuid: base64.b64encode(bytes.fromhex(uuid.replace('-', ''))).replace(b'+', b'-').replace(b'/', b'_').rstrip(b'=').decode('ascii')
BaseTemplate.defaults['config'] = app.config
BaseTemplate.defaults['get_url'] = app.get_url

def parse_note_tags(note):
    def split_tags(tag_line):
        yield from (
            i
            for i in re.split(r'[` ,]+', tag_line)
            if i
        )

    def find_tag_lines(note):
        meta_section = \
                note.split('---\n')[1] \
                if note.startswith('---\n') else \
                ''

        meta_tags = ''

        for line in meta_section.split('\n'):
            line = line.strip()
            if line.startswith('tags:'):
                # FIXME: should we return only last `tags:`?
                yield line[5:]

        for tags in re.findall(r'######\s*tags:\s*(?P<tags>.+)', note):
            yield tags

    for tag_line in find_tag_lines(note):
        yield from split_tags(tag_line.strip())


@app.get('/')
def index():
    return redirect(app.get_url('/recently-updated'))

@app.get('/recently-updated')
@app.get('/recently-updated/<page:int>', name='recently-updated')
@view('recently-updated')
def recently_updated(page=0):
    cursor = db.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cursor.execute('''
            SELECT
                COUNT("Notes"."id")
            FROM "Notes"
            JOIN "Users"
                ON "Users"."id" = "Notes"."ownerId"
            WHERE
                "Notes"."title" != 'Untitled' AND
                "Notes"."permission" != 'private'
            ''')
    item_count = cursor.fetchone()[0]
    per_page = int(app.config['pager.item_per_page'])
    page_count = (item_count + per_page) // per_page
    #page = int(request.params.get('page', 1))
    if page < 0:
        page = 0
    elif page > page_count:
        page = page_count

    cursor.execute('''
            SELECT
                "Notes"."id",
                "Notes"."title",
                "Notes"."content",
                "Notes"."lastchangeAt",
                "Notes"."createdAt",
                "Notes"."permission",
                "Users"."email" AS "owner"
            FROM "Notes"
            JOIN "Users"
                ON "Users"."id" = "Notes"."ownerId"
            WHERE
                "Notes"."title" != 'Untitled' AND
                "Notes"."permission" != 'private'
            ORDER BY
                "Notes"."lastchangeAt" DESC
            LIMIT %s OFFSET %s
            ''', (per_page, page * per_page))

    notes = [
        { 'tags': list(parse_note_tags(note['content'])), **note }
        for note in cursor
    ]

    notes = [
        note for note in notes
        if 'private' not in note['tags']
    ]

    return {
        'notes': notes,
        'page_count': page_count,
        'current_page': page,
    }

if __name__ == '__main__':
    run(app, host='0.0.0.0', port='8080', server='waitress', debug=True, reloader=True)
