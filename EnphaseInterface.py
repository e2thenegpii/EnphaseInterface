
import urllib.parse as p
import urllib.request as r
import datetime as dt
import dateutil.parser as dp
import json
import time
import logging

from lxml import etree as et
from pandas import Series,to_timedelta,to_datetime,concat,DataFrame
from pandas.io.json import json_normalize
from enum import Enum

APIV2 = 'https://api.enphaseenergy.com/api/v2'
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
        elif self is DateTimeType.Iso8601:
            return d.isoformat()
        elif self is DateTimeType.Epoch:
            return str(int(d.timestamp()))
        logging.warning('Failed to stringify %s' % value)
            
    def datetimeify(self, key, value):
        '''Convert an Enphase timestamp or time string to a datetime'''
        
        if self is DateTimeType.Enphase:
            if '_date' in key:
                return dt.datetime.strptime(value,'%Y-%m-%d')
            else:
                return dt.datetime.fromtimestamp(value)
        elif self is DateTimeType.Iso8601:
            return dp.parser.parse(value) 
        elif self is DateTimeType.Epoch:
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

        for k,v in query.items():
            if '_at' in k or '_date' in k:
                if v > dt.datetime.now():
                    logging.error('The value for %s is set to the future' % k)
                    raise ValueError('A query with a future time is malformed')
                query[k] = self.stringify(k,v)

class EnphaseOutputWrapperRaw(object):
    '''Package up the output data in a raw format'''
    def convert(self, datatype, data, dtt):
        return data
        
class EnphaseOutputWrapperJson(EnphaseOutputWrapperRaw):
    '''Package up the output data in a json format'''
    def convert(self, datatype, data, dtt):
        return json.loads(data.decode(encoding='UTF-8'))
        
class EnphaseOutputWrapperPandas(EnphaseOutputWrapperRaw):
    '''Package up the output data in a pandas dataframe'''

    def _energy_lifetime(self,data,dtt):
        d = json_normalize(data, 'production',['start_date','system_id'])
        ts = to_timedelta(Series(d.index),unit='D')
        d['start_date'] = to_datetime(d['start_date'],unit='s') + ts
        d['start_date'] = d['start_date'].apply(
                lambda x:dtt.stringify('start_date',x))
        d.rename(columns={0:'production'},inplace=True)

        return d.set_index(['system_id','start_date'])

    def _envoys(self,data):
        return json_normalize(data, 'envoys',
            ['system_id']).set_index(['system_id','serial_number'])

    def _index(self,data):
        return json_normalize(data,'systems').set_index('system_id')

    def _inventory(self,data):
        cl = []
        for key in ['inverters','envoys','meters']:
            if key in data:
                cl.append(json_normalize(data,key,['system_id']))
            #this assumes only the envoys don't return the model type
        tmp = concat(cl).fillna('Envoy').set_index(['system_id','sn'])
        #normalize the index
        tmp.index.name = ['system_id','serial_number']
        return tmp

    def _monthly_production(self,data):
        if len(data['meter_readings']) > 0:
            output = json_normalize(data,'meter_readings',
                ['start_date','system_id','end_date','production_wh'])
        else:
            output = json_normalize(data,meta=
                    ['start_date','system_id','end_date','production_wh'])
        return output.set_index(['system_id','start_date','end_date'])

    def _stats(self,data):
        if len(data['intervals']) > 0:
            output = json_normalize(data,'intervals',
                ['system_id','total_devices']).set_index(['system_id',
                    'end_at'])
        else:
            output = json_normalize(data).set_index('system_id')
        return output

    def _summary(self,data):
        return json_normalize(data).set_index('system_id')

    def _datetimeify(self,output,dtt):
        indexes = output.index.names
        output.reset_index(inplace=True)
        for col in output.columns:
            if '_at' in col or '_date' in col:
                output[col] = output[col].apply(lambda x:dtt.datetimeify(col,x))
        return output.set_index(indexes)

    def convert(self, datatype, data, dtt):

        data = json.loads(data.decode(encoding='UTF-8'))
        logging.debug(data)

        if datatype == 'energy_lifetime':
            output = self._energy_lifetime(data,dtt)
        elif datatype == 'envoys':
            output = self._envoys(data)
        elif datatype == 'index' or datatype == '':
            output = self._index(data)
        elif datatype == 'inventory':
            output = self._inventory(data)
        elif datatype == 'monthly_production':
            output = self._monthly_production(data)
        elif datatype == 'rgm_stats':
            output = self._stats(data)
        elif datatype == 'stats':
            output = self._stats(data)
        elif datatype == 'summary':
            output = self._summary(data)
        else:
            raise ValueError('datatype parameter not supported')

        return self._datetimeify(output,dtt)

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
        return self.outputWrapper.convert(command[1:],self.opener.open(req).read(),
                self.dtt)
        
    def setDateTimeType(self, dtt):
        '''Set the timestamp type for the Enphase API'''

        self.parameters['datetime_format'] = dtt.value
        self.handler.setDateTimeType(dtt)
        
        if dtt is DateTimeType.Enphase:
            self.parameters.pop('datetime_format',None)
            
    def setOutputWrapper(self, outputWrapper):
        self.outputWrapper = outputWrapper
            
    @staticmethod
    def _processPage(request):
        logging.debug(request.geturl())

        root = et.HTML(request.read().decode(encoding='UTF-8'))
        form = root.find('.//form[@action]')

        payload = {}
        for node in root.findall('.//input[@type="hidden"]'):
            payload[node.attrib['name']] = node.attrib['value']

        return (form.attrib['action'],payload)

    @staticmethod
    def authorizeApplication(app_id, username, password):
        '''Authorize an application to access a systems data
            and get the user_id'''

        scheme = 'https'
        base_url = 'enlighten.enphaseenergy.com'
        action = 'app_user_auth/new'
        query = p.urlencode({'app_id':app_id})

        request1 = p.urlunsplit((scheme,base_url,action,query,''))
        logging.debug(request1)

        opener = r.build_opener(r.HTTPCookieProcessor())
        opener.addheaders = [('User-agent','Mozilla/5.0')]
        r1 = opener.open(request1)

        action,hiddens = EnphaseInterface._processPage(r1)

        payload = {'user[email]':username,'user[password]':password}
        hiddens.update(payload)

        request2 = p.urlunsplit((scheme,base_url,action,query,''))
        r2 = opener.open(request2,p.urlencode(hiddens).encode(encoding='UTF-8'))
        action, hiddens = EnphaseInterface._processPage(r2)

        request3 = p.urlunsplit((scheme,base_url,action,query,''))
        r3 = opener.open(request3,p.urlencode(hiddens).encode(encoding='UTF-8'))

        if 'enlighten-api-user-id' not in r3.info():
            logging.critical('Failed to aquire user_id')

        logging.debug(r3.info()['enlighten-api-user-id'])
        return r3.info()['enlighten-api-user-id']

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

    def monthly_production(self, system_id, **kwargs):
        '''List the energy produced in the last month'''

        if 'start_date' not in kwargs:
            raise AttributeError('start_date required parameter')
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
