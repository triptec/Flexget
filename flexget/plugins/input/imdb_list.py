from __future__ import unicode_literals, division, absolute_import
import logging
import feedparser
import re
from cgi import parse_header

from flexget import plugin
from flexget.event import event
from flexget.utils import requests
from flexget.utils.imdb import make_url, extract_id
from flexget.utils.cached_input import cached
from flexget.utils.tools import decode_html
from flexget.entry import Entry
from flexget.utils.soup import get_soup

log = logging.getLogger('imdb_list')

USER_ID_RE = r'^ur\d{7,8}$'


class ImdbList(object):
    """"Creates an entry for each movie in your imdb list."""

    schema = {
        'type': 'object',
        'properties': {
            'user_id': {
                'type': 'string',
                'pattern': USER_ID_RE,
                'error_pattern': 'user_id must be in the form urXXXXXXX'
            },
            'username': {'type': 'string'},
            'password': {'type': 'string'},
            'list': {'type': 'string'}
        },
        'required': ['list'],
        'additionalProperties': False
    }

    @cached('imdb_list', persist='2 hours')
    def on_task_input(self, task, config):
        sess = requests.Session()
        if config.get('username') and config.get('password'):

            log.verbose('Logging in ...')

            # Log in to imdb with our handler
            params = {'login': config['username'], 'password': config['password']}
            try:
                # First get the login page so we can get the hidden input value
                soup = get_soup(sess.get('https://secure.imdb.com/register-imdb/login').content)

                # Fix for bs4 bug. see #2313 and github#118
                auxsoup = soup.find('div', id='nb20').next_sibling.next_sibling
                tag = auxsoup.find('input', attrs={'name': '49e6c'})
                if tag:
                    params['49e6c'] = tag['value']
                else:
                    log.warning('Unable to find required info for imdb login, maybe their login method has changed.')
                # Now we do the actual login with appropriate parameters
                r = sess.post('https://secure.imdb.com/register-imdb/login', data=params, raise_status=False)
            except requests.RequestException as e:
                raise plugin.PluginError('Unable to login to imdb: %s' % e.message)

            # IMDb redirects us upon a successful login.
            # removed - doesn't happen always?
            # if r.status_code != 302:
            #     log.warning('It appears logging in to IMDb was unsuccessful.')

            # try to automatically figure out user_id from watchlist redirect url
            if not 'user_id' in config:
                log.verbose('Getting user_id ...')
                try:
                    response = sess.get('http://www.imdb.com/list/watchlist')
                except requests.RequestException as e:
                    log.error('Error retrieving user ID from imdb: %s' % e.message)
                    user_id = ''
                else:
                    log.debug('redirected to %s' % response.url)
                    user_id = response.url.split('/')[-2]
                if re.match(USER_ID_RE, user_id):
                    config['user_id'] = user_id
                else:
                    raise plugin.PluginError('Couldn\'t figure out user_id, please configure it manually.')

        if not 'user_id' in config:
            raise plugin.PluginError('Configuration option `user_id` required.')

        log.verbose('Retrieving list %s ...' % config['list'])

        # Get the imdb list in RSS format
        try:
            if config['list'] in ['watchlist', 'ratings', 'checkins']:
                url = 'http://rss.imdb.com/user/%s/%s' % (config['user_id'], config['list'])
            else:
                url = 'http://rss.imdb.com/list/%s' % config['list']
            log.debug('Requesting %s' % url)
            try:
                rss = feedparser.parse(url)
            except LookupError as e:
                raise plugin.PluginError('Failed to parse RSS feed for list `%s` correctly: %s' % (config['list'], e))
        except requests.RequestException as e:
            raise plugin.PluginError('Unable to get imdb list: %s' % e.message)

        # Create an Entry for each movie in the list
        entries = []
        for entry in rss.entries:
            try:
                entries.append(Entry(title=entry.title, url=entry.link, imdb_id=extract_id(entry.link), imdb_name=entry.title))
            except IndexError:
                log.critical('IndexError! Unable to handle RSS entry: %s' % entry)
        return entries


@event('plugin.register')
def register_plugin():
    plugin.register(ImdbList, 'imdb_list', api_ver=2)
