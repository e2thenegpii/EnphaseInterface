
import urllib.parse as p
import urllib.request as r
import json
import time

APIV2 = 'https://api.enphaseenergy.com/api/v2/'
APIKEY = ''

DEFAULT_MAX_WAIT = 60

class EnphaseUnprocessable(BaseHandler):
	def __init__(self):
		super(BaseHandler,self).__init__(self)
		
	def http_error_422(req, fp, code, msg, hdrs):
		#figure out what returned the unprocessable error and correct items
		pass

class EnphaseRateLimit(BaseHandler):
	def __init__(self, max_wait = DEFAULT_MAX_WAIT):
		super(BaseHandler,self).__init__(self)
		
		self.max_wait = max_wait
	
	def setMaxWait(max_wait):
		self.max_wait = max_wait
		
	def http_error_409(req, fp, code, msg, hdrs):
		#parse the msg and get the wait time
		#if the wait time is longer then max wait raise an error
		#else sleep
		pass
		
	def http_error_503(req, fp, code, msg, hdrs):
		#The api says if you have made to many concurrent requests
		#then you will get a http_error_503, but they say nothing else
		pass

class EnphaseInterfaceRaw(object):
	"Interfaces with the Enphase api and returns the raw json"
	
	EnphaseInterfaceRaw.DatetimeType.Enphase = 'enphase'
	EnphaseInterfaceRaw.DatetimeType.Iso8601 = 'iso8601'
	EnphaseInterfaceRaw.DatetimeType.Epoch   = 'epoch'
	
	def __init__(self, userId, max_wait=DEFAULT_MAX_WAIT):
		if APIKEY == '':
			raise ValueError("APIKEY not set")

		self.parameters = { 'user_id': userId,
							'key': APIKEY }
							
		self.rateLimit = EnphaseRateLimit(max_wait)
							
		self.opener = r.build_opener([self.rateLimit])
		self.apiDest = APIV2
							
	def _execQuery(self, system_id, command, extraParams = dict()):
		q = p.urlencode(self.parameters)
		q += p.urlencode(extraParams)
		
		query = self.apiDest + system_id + '/' command + '?' + q
		
		return self.opener.open(query)
		
	def setDatetimeType(type):
		self.parameters['datetime_format'] = type
		
		if type == EnphaseInterfaceRaw.DatetimeType.Enphase:
			self.parameters.pop('datetime_format',None)

	def energy_lifetime(system_id, start_date, end_date):
		pass
	def envoys(system_id):
		pass
	def index(**kwargs):
		sysAttributes = ['system_id', 'system_name', 'status', 'reference', 
							'installer', 'connection_type']

		uset = set(kwargs.keys()) & set(sysAttributes)
		if len(uset) > 1:
			for x in uset:
				kwargs[x+'[]'] = kwargs.pop(x)
	
class EnphaseInterfacePandas(EnphaseInterfaceRaw):
	"Wraps all the data returned from Enphase as a pandas dataframe"
	pass

class EnphaseInterface(EnphaseInterfaceRaw):
	"Wraps all the data returned as a regular python dictionary"
	pass