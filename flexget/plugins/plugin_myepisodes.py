import logging
import urllib
import urllib2
import re
import cookielib
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from flexget import schema
from flexget.plugin import register_plugin, DependencyError


try:
    from flexget.plugins.api_tvdb import lookup_series
except ImportError:
    raise DependencyError(issued_by='myepisodes', missing='api_tvdb',
                          message='myepisodes requires the `api_tvdb` plugin')


log = logging.getLogger('myepisodes')
Base = schema.versioned_base('myepisodes', 0)


class MyEpisodesInfo(Base):
    __tablename__ = 'myepisodes'

    id = Column(Integer, primary_key=True)
    series_name = Column(String, unique=True) # don't know if unique is correct python syntax for saying there must only be one entry with the same content
    myepisodes_id = Column(Integer, unique=True)
    updated = Column(DateTime)

    def __init__(self, series_name, myepisodes_id):
        self.series_name = series_name
        self.myepisodes_id = myepisodes_id
        self.updated = datetime.now()

    def __repr__(self):
        return '<MyEpisodesInfo(series_name=%s, myepisodes_id=%s)>' % (self.series_name, self.myepisodes_id)


class MyEpisodes(object):
    """
    Marks a series episode as acquired in your myepisodes.com account.

    Simple Example:
    Most shows are recognized automatically from their TVDBname. And of course the plugin needs to know your MyEpisodes.com account details.

    feeds:
      tvshows:
        myepisodes:
          username: <username>
          password: <password>
        series:
         - human target
         - chuck

    Advanced Example:
    In some cases, the TVDB name is either not unique or won't even be discovered. In that case you need to specify the MyEpisodes id manually using the set plugin.
    feeds:
      tvshows:
        myepisodes:
          username: <username>
          password: <password>
        series:
         - human target:
             set:
               myepisodes_id: 5111
         - chuck

    How to find the MyEpisodes id: http://matrixagents.org/screencasts/myep_example-20110507-131555.png
    """

    def validator(self):
        from flexget import validator
        root = validator.factory('dict')
        root.accept('text', key='username', required=True)
        root.accept('text', key='password', required=True)
        return root

    def on_feed_exit(self, feed, config):
        """Mark all accepted episodes as acquired on MyEpisodes"""
        if not feed.accepted:
            # Nothing accepted, don't do anything
            return

        username = config['username']
        password = config['password']

        cookiejar = cookielib.CookieJar()
        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cookiejar))
        baseurl = urllib2.Request('http://myepisodes.com/login.php?')
        loginparams = urllib2.urlencode({'username': username,
                                        'password': password,
                                        'action': 'Login'})
        try:
            logincon = opener.open(baseurl, loginparams)
            loginsrc = logincon.read()
        except urllib2.URLError, e:
            log.error('Error logging in to myepisodes: %s' % e)
            return

        if str(username) not in loginsrc:
            log.error("Login to myepisodes.com failed, please check your account data or see if the site is down.")
            return

        for entry in feed.accepted:
            self.mark_episode(feed, entry, opener)

    def lookup_myepisodes_id(self, entry, opener, session):
        """Populates myepisodes_id field for an entry, and returns the id."""

        # Don't need to look it up if we already have it.
        if entry.get('myepisodes_id'):
            return entry['myepisodes_id']

        if not entry.get('series_name'):
            raise LookupError('Cannot lookup myepisodes id for entries without series_name')
        series_name = entry['series_name']

        # First check if we already have a myepisodes id stored for this series
        myepisodes_info = session.query(MyEpisodesInfo).filter(MyEpisodesInfo.series_name == series_name.lower()).first()
        if myepisodes_info:
            entry['myepisodes_id'] = myepisodes_info.myepisodes_id
            return myepisodes_info.myepisodes_id

        # Get the series name from thetvdb to increase match chance on myepisodes
        if entry.get('series_name_tvdb'):
            tvdb_name = entry['series_name_tvdb']
        else:
            try:
                series = lookup_series(name=series_name, tvdb_id=entry.get('thetvdb_id'))
                tvdb_name = series.seriesname
            except LookupError, e:
                log.warning('Unable to lookup series %s from tvdb, using raw name.' % series_name)
                tvdb_name = series_name

        baseurl = urllib2.Request('http://myepisodes.com/search.php?')
        params = urllib.urlencode({'tvshow': tvdb_name, 'action': 'Search myepisodes.com'})
        try:
            con = opener.open(baseurl, params)
            txt = con.read()
        except urllib2.URLError, e:
            log.error('Error searching for myepisodes id: %s' % e)

        matchObj = re.search(r'&showid=([0-9]*)">' + tvdb_name + '</a>', txt, re.MULTILINE | re.IGNORECASE)
        if matchObj:
            myepisodes_id = matchObj.group(1)
            db_item = session.query(MyEpisodesInfo).filter(MyEpisodesInfo.myepisodes_id == myepisodes_id).first()
            if db_item:
                log.info('Changing name to %s for series with myepisodes_id %s' % (series_name.lower(), myepisodes_id))
                db_item.myepisodes_id = myepisodes_id
            else:
                session.add(MyEpisodesInfo(series_name.lower(), myepisodes_id))
            entry['myepisodes_id'] = myepisodes_id
            return myepisodes_id

    def mark_episode(self, feed, entry, opener):
        if not self.lookup_myepisodes_id(entry, opener, session=feed.session):
            log.warning('Couldn\'t get myepisodes id for %s' % entry['title'])
            return

        if 'series_season' not in entry or 'series_episode' not in entry:
            log.warning('Can\'t mark entry in myepisodes without series_season and series_episode fields')
            return

        myepisodes_id = entry['myepisodes_id']
        season = entry['series_season']
        episode = entry['series_episode']

        if feed.manager.options.test:
            log.info('Would mark %s of `%s` as acquired.' % (entry['series_id'], entry['series_name']))
        else:
            baseurl2 = urllib2.Request('http://myepisodes.com/myshows.php?action=Update&showid=%s&season=%s&episode=%s&seen=0' % (myepisodes_id, season, episode))
            opener.open(baseurl2)
            log.info('Marked %s of `%s` as acquired.' % (entry['series_id'], entry['series_name']))


register_plugin(MyEpisodes, 'myepisodes', api_ver=2)