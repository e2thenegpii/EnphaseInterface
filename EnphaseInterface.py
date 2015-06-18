
import urllib.parse as p
import urllib.request as r
import datetime as dt
import dateutil.parser as dp
import json
import time
import logging

import http.cookiejar as cj
from lxml import etree as et

from enum import Enum

APIV2 = 'https://api.enphaseenergy.com/api/v2'
APPAUTH = 'https://enlighten.enphaseenergy.com/app_user_auth/new'
APIKEY = ''

DEFAULT_MAX_WAIT = 60

class EnphaseErrorHandler(r.BaseHandler):
    def __init__(self, datetimetype, max_wait = DEFAULT_MAX_WAIT):
        super(EnphaseErrorHandler,self).__init__()

        self.dtt = datetimetype
        self.max_wait = max_wait
        logging.debug('Initialized EnphaseErrorHandler')
    
    def setMaxWait(self, max_wait):
        self.max_wait = max_wait
        logging.debug('Set max_wait to %d' % self.max_wait)
        
    def setDateTimeType(self, dtt):
        self.dtt = dtt
        logging.debug('Set DateTimeType to %s' % self.dtt.value)
        
    def http_error_409(self, req, fp, code, msg, hdrs):

        s = fp.read().decode(encoding='UTF-8')
        data = json.loads(s)

        logging.info('Received HTTP Error 409')
        logging.debug(data)

        end = self.dtt.datetimeify('period_end',data['period_end'])
        diff = end.timestamp() - int(time.time())

        if diff < self.max_wait:
            logging.info('Sleeping for %f seconds' % diff+1)
            time.sleep(diff+1) #sleep +1 to prevent a second 409
            return r.build_opener(self).open(req.get_full_url())
        
    def http_error_422(self, req, fp, code, msg, hdrs):

        s = fp.read().decode(encoding='UTF-8')
        data = json.loads(s)
        
        logging.info('Received HTTP Error 422')
        logging.debug(data)

        if 'Failed to parse date' in data['reason']:
            logging.error(req.get_full_url())
            logging.error(data)
            return

        if 'Requested date range is invalid for this system' in data['reason']:
            logging.error(req.get_full_url())
            logging.error(data)
            return

        startAt = self.dtt.datetimeify('start_at',data['start_at'])
        lastInt = self.dtt.datetimeify('last_interval', data['last_interval'])

        if startAt > lastInt:
            endAt = self.dtt.datetimeify('end_at',data['end_at'])
            startAt = dt.combine(endAt.date(),datetime.time())

            s,n,pa,pr,q,f = p.urlparse(req.get_full_url())
            params = dict(p.parse_qsl(q))
            params['start_at'] = self.dtt.stringify('start_at',
                    startAt.timestamp())
            qstring = p.urlencode(params)
            url = p.urlunparse((s,n,pa,pr,qstring,f))
            return r.build_opener(self).open(url)
        #handle other potential error cases

    def http_error_503(self, req, fp, code, msg, hdrs):
        #The api says if you have made to many concurrent requests
        #then you will get a http_error_503, but they say nothing else
        pass

class DateTimeType(Enum):
    Enphase = 'enphase'
    Iso8601 = 'iso8601'
    Epoch   = 'epoch'
    
    def stringify(self, key, value):
        '''Convert the datetime values to the correct format'''
        
        d = value.replace(microsecond=0)
        if self is DateTimeType.Enphase:
            if '_date' in key:
                return d.strftime('%Y-%m-%d')
            else:
                return str(int(d.timestamp()))
        elif self is Iso8601:
            return d.isoformat()
        elif self is Epoch:
            return str(int(d.timestamp()))
        logging.warning('Failed to stringify %s' % value)
            
    def datetimeify(self, key, value):
        '''Convert an Enphase timestamp or time string to a datetime'''
        
        if self is DateTimeType.Enphase:
            if '_date' in key:
                return dt.datetime.strftime('%Y-%m-%d')
            else:
                return dt.datetime.fromtimestamp(value)
        elif self is Iso8601:
            return dp.parser.parse(value) 
        elif self is Epoch:
            return dt.datetime.fromtimestamp(value)
        logging.warning('Failed to datetimeify %s' % value)
        
    def sanatizeTimes(self, query):
        '''Make sure the datetime values are sane'''
        
        if 'start_at' in query and 'end_at' in query:
            if query['start_at'] > query['end_at']:
                logging.error('The value for start_at is after end_at')
                raise ValueError('start_at is after end_at')
        elif 'start_date' in query and 'end_date' in query:
            if query['start_date'] > query['end_date']:
                logging.error('The value for start_date is after end_date')
                raise ValueError('start_date is after end_date')
            
        for k,v in query:
            if '_at' in k or '_date' in k:
                if v > dt.datetime.now():
                    logging.error('The value for %s is set to the future' % k)
                    raise ValueError('A query with a future time is malformed')
                query[k] = self.stringify(k,v)

class EnphaseOutputWrapperRaw(object):
    '''Package up the output data in a raw format'''
    def convert(self, data):
        return data
        
class EnphaseOuptutWrapperJson(EnphaseOuptutWrapperRaw):
    '''Package up the output data in a json format'''
    def convert(self, data):
        return json.loads(data.decode(encoding='UTF-8'))
        
class EnphaseOutputWrapperPandas(EnphaseOutputWrapperRaw):
    '''Package up the output data in a pandas dataframe'''
    def convert(self, data):
        raise NotImplementedError()
        return data

class EnphaseInterface(object):
    '''Interfaces with the Enphase api and returns the raw json
        It expects all dates and times to be in a child of a datetime type'''

    def __init__(self, userId, max_wait=DEFAULT_MAX_WAIT, 
        wrapper = EnphaseOutputWrapperRaw()):
        if APIKEY == '':
            raise ValueError("APIKEY not set")

        self.parameters = { 'user_id': userId,
                            'key': APIKEY }
        
        self.dtt = DateTimeType.Enphase
        self.handler = EnphaseErrorHandler(self.dtt, max_wait)
                            
        self.opener = r.build_opener(self.handler)
        self.apiDest = APIV2
        self.appauth = APPAUTH
        self.outputWrapper = wrapper

    def _execQuery(self, system_id, command, extraParams = dict()):
        '''Generates a request url for the Enphase API'''

        if system_id is not '':
            system_id = '/' + system_id
        if command is not '':
            command = '/' + command

        query = dict(self.parameters)
        query.update(extraParams)

        self.dtt.sanatizeTimes(query)

        q = p.urlencode(query)

        query = self.apiDest + '/systems' + system_id + command + '?' + q
        req = r.Request(query, headers={'Content-Type':'application/json'})
        
        logging.debug('GET %s' % query)
        return self.outputWrapper.convert(self.opener.open(req).read())
        
    def setDateTimeType(self, dtt):
        '''Set the timestamp type for the Enphase API'''

        self.parameters['datetime_format'] = dtt.value
        self.handler.setDateTimeType(dtt)
        
        if dtt is DateTimeType.Enphase:
            self.parameters.pop('datetime_format',None)
            
    def setOutputWrapper(self, outputWrapper):
        self.outputWrapper = outputWrapper
            
    def authorizeApplication(self, app_id, username, password):
        '''Authorize an application to access a systems data
            and get the user id'''

        cookiefile = 'e.cookies'
        jar = cj.FileCookieJar(cookiefile)
        jar.save()

        opener = r.build_opener(r.HTTPCookieProcessor(jar))
        opener.addheaders = [('User-agent':'Mozilla/5.0')]
        
        q = p.urlencode({'app_id':app_id})
        query = self.appauth + '?' + q

        response = opener.open(query)
        jar.save()

        root = et.fromstring(response.readall())

        login_data = {'user[email]':username,'user[password]':password}
        
        #hiddenInput = root.find(".//input[@name='authenticity_token'"])        
        for node in root.findall('.//input[@type="hidden"]'):
            login_data[node.attrib['name']] = node.attrib['value']

        data = p.urlencode(login_data)

        response = opener.open(response.geturl(), data)
        jar.save()
        
        login_data.pop('user[email]')
        login_data.pop('user[password]')
        login_data['app_user_auth[tscale_app_id]'] = app_id
        
        data = p.urlencode(login_data)
        response = opener.open(response.geturl(),data)
        jar.save()

        return response.info()['enlighten-api-user-id']

    def energy_lifetime(self, system_id, **kwargs):
        '''Get the lifetime energy produced by the system'''

        return self._execQuery(system_id, 'energy_lifetime', kwargs)

    def envoys(self, system_id, **kwargs):
        '''List the envoys associated with the system'''

        return self._execQuery(system_id, 'envoys', kwargs)
    
    def index(self, **kwargs):
        '''List the systems available by this API key'''

        sysAttributes = ['system_id', 'system_name', 'status', 'reference', 
                            'installer', 'connection_type']

        uset = set(kwargs.keys()) & set(sysAttributes)
        if len(uset) > 1:
            for x in uset:
                kwargs[x+'[]'] = kwargs.pop(x)

        return self._execQuery('', '', kwargs)

    def inventory(self, system_id, **kwargs):
        '''List the inverters associated with this system'''

        return self._execQuery(system_id, 'inventory', kwargs)

    def monthly_production(self, system_id, start_date, **kwargs):
        '''List the energy produced in the last month'''

        return self._execQuery(system_id, 'monthly_production', kwargs)

    def rgm_stats(self, system_id, **kwargs):
        '''List the Revenue Grade Meter stats'''

        return self._execQuery(system_id, 'rgm_stats', kwargs)

    def stats(self, system_id, **kwargs):
        '''Get the 5 minute interval data for the given day'''

        return self._execQuery(system_id, 'stats', kwargs)

    def summary(self, system_id, **kwargs):
        '''Get the system summary'''

        return self._execQuery(system_id, 'summary', kwargs)
