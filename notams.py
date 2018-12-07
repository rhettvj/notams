# . venv/bin/activate
# export FLASK_APP=notams.py
# export FLASK_DEBUG=1
# flask run

from flask import Flask, render_template, request, flash, Markup
import requests
import re
import datetime
import sys
import operator

app = Flask(__name__)
app.secret_key = 'nsecret'
g_error_str = ""
DEFAULT_AID = "CYTR"
# List order:
#  Notam File
#		Category
#			Score
#
#holds list of categories
class nFile:
	name = ""
	num_notams = 0
	valid = True
	c_list = None
	sorted_c_list = None
	alert = False
	def __init__(self, file_name):
		self.name = file_name
		self.c_list = {}

	def add(self, n, parent_list):
		if n.category not in self.c_list:
			self.c_list[n.category] = Category(n.category, parent_list)
		self.c_list[n.category].add(n)
		if n.alert:
			self.alert = True
		self.num_notams += 1

class CategoryParent:
	name = ""
	priority = 0
	full_name = ""
	hide = False

#holds list of notams
class Category:
	name = ""
	n_list = None
	num_notams = 0
	priority = 0
	full_name = ""
	hide = False
	def __init__(self, name, parent_list):
		if name in parent_list:
			self.priority = parent_list[name].priority
			self.full_name = parent_list[name].full_name
			self.hide = parent_list[name].hide
		self.name = name
		self.n_list = []
	def add(self, n):
		self.n_list.append(n)
		self.num_notams += 1
	def get_priority():
		return self.priority

class Wx:
	origin_code = ""
	text = ""
	category = None
	alert = False
	def __init__(self, origin_code, text):
		self.origin_code = origin_code
		self.text = text
		self.category = "WX" #set for all wx lines

class Notam:
	origin_code = ""
	origin_name = ""
	text = ""

	dt_issue_time = None
	dt_from_time = None
	dt_till_time = None

	issue_time_str = ""
	from_time_str = ""
	till_time_str = ""

	issue_time_casual = ""
	from_time_casual = ""
	till_time_casual = ""

	recent = False
	date_score = 0 #alters score based on date
	score = 0 #orders notams within a category
	tags = "" #list of multiple tags
	category = None #there can be only one
	alert = False

	def __init__(self, origin_code, origin_name, dt_issue_time, dt_from_time, dt_till_time, text):
		self.origin_code = origin_code
		self.origin_name = origin_name

		if dt_issue_time: self.dt_issue_time = dt_issue_time
		if dt_from_time: self.dt_from_time = dt_from_time
		if dt_till_time: self.dt_till_time = dt_till_time
		self.set_dates()
		self.text = text
		self.tags = ""
		self.category = "MISC"

	def set_dates(self):
		self.issue_time_str = date_to_str(self.dt_issue_time)
		self.from_time_str = date_to_str(self.dt_from_time)
		self.till_time_str = date_to_str(self.dt_till_time)
		self.issue_time_casual = date_to_casual(self.dt_issue_time)
		self.from_time_causal = date_to_casual(self.dt_from_time)
		self.till_time_casual = date_to_casual(self.dt_till_time)

	def add_tags(self, tag):
		self.tags = self.tags + " [" + "]"




class Rule:
	abbrev = ""
	keyword = False #search for abbrev in text to apply rule
	score = 0
	full = None
	category = ""


@app.route('/', methods= ['POST', 'GET'])
def main():
	notams = [] #used initially to store all notams and parse/tag/score
	nfiles = None #dictionary of files into which they'll eventually be distributed
					# filename : nFile
	a_id = None
	category_parents_list = {}
	tz_diff = -0
	if request.method == 'POST':
		result=request.form

		splt = result["aid"].upper().split()
		for word in splt:
			if word[0:2].upper() == "TZ" and (word[2:3] == '-' or word[2:3] == '+'):
				if word[3:4].isdigit():
					tz_diff = int(word[2:4])
					splt.remove(word)
		a_id = ' '.join(splt)

	if a_id and result["product"] == "notams":
		html = download_file(a_id, "notams")
		raw_list = find_notams(html)
		nfiles = {}
		rule_list = load_rules("rules", category_parents_list)
		for raw_notam in raw_list:
			n = parse_notam(raw_notam)
			apply_rules(n, rule_list)
			file_notam(n, nfiles, category_parents_list) #add notams to category lists within files
		for f in nfiles.values(): #go thru each file
			for c in f.c_list.values(): #go thru each category
				#sort each notam (notams are in [] lists)
				c.n_list = sorted(c.n_list, key=operator.attrgetter('score'))
		#and then sort the categories themselves (categories are in {} dicts)
			f.sorted_c_list = sorted(f.c_list.values(), key=operator.attrgetter('priority')) #key=operator.attrgetter('priority'))		


	elif a_id and result["product"] == "weather":
		html = download_file(a_id, "weather")
		raw_list = find_weather_lines(html)
		nfiles = {}
		pcat = CategoryParent()
		pcat.name = "WX"
		pcat.full_name = "METAR-TAF"
		pcat.priority = 0
		category_parents_list["WX"] = pcat
		for raw_wx in raw_list:
			n = parse_wx(raw_wx, tz_diff)
			file_notam(n, nfiles, category_parents_list)

		for f in nfiles.values():
			#this is a little hacky but there will be only be 1 category (WX)
			#the template is expecting a 'view', not a dict and this seems like an easy way to 
			#produce a view
			f.sorted_c_list = sorted(f.c_list.values(), key=operator.attrgetter('priority'))
	elif a_id is None:
            a_id = DEFAULT_AID
	a_id = "TZ" + str(tz_diff) + " " + a_id
	return render_template('header.html', files=nfiles, aid=a_id)


#RULES
def apply_rules(n, rule_list):
	#score_on_dates(n)
	n.score += n.date_score
	kw_found = False #can only be scored on one keyword
	for r in rule_list:
		if r.keyword is True:
			if re.search("\s" + r.abbrev + "\W", n.text) is not None:	
				if kw_found == False: #no keywords found yet
					n.score += r.score #score on this keyword
					n.add_tags(r.abbrev)
					kw_found = True
					if r.category is not None:
						n.category = r.category
				if r.full:
						if r.full[0:1] == '(': #if full name is in brackets, add it after the abbrev
							n.text = n.text.replace(r.abbrev, r.abbrev + " " + r.full)
						else: #if it's just to make reading easier, replace it fully
							n.text = n.text.replace(r.abbrev, r.full)
		elif r.abbrev == "VICTORS":
			if kw_found == True:
				continue
			if re.search("V\d{2}", n.text) is not None:
				n.score += r.score
				n.category = r.category
				kw_found = True
				n.add_tags(r.abbrev)

def file_notam(n, file_list, parent_list):
	#create file for origin code if it doesn't already exist
	if n.origin_code:
		if n.origin_code not in file_list:
			file_list[n.origin_code] = nFile(n.origin_code)
		#add to the notam to the file. the file itself will categorize it	
		file_list[n.origin_code].add(n, parent_list)
	else:
		err("Origin code not found for item " + n.text)

#RULES
def load_rules(filename, category_parents_list):
	#f = open(filename, "r")
	with app.open_resource(filename) as f:
		rule_list = []
		for line in f:
			if line:
					line = line.decode('UTF-8') #because open_resource apparently spits out bytes
					if line[0:1] == "#" or len(line) < 5:
						continue
					elif line[0:8] == "CATEGORY":
						c_list = line.split()
						this_parent_cat = CategoryParent()
						this_parent_cat.abbrev = c_list[1]
						this_parent_cat.priority = int(c_list[2])
						this_parent_cat.hide = True if int(c_list[3]) > 0 else False
						this_parent_cat.full_name = c_list[4]
						category_parents_list[this_parent_cat.abbrev] = this_parent_cat
					else:
						this_rule = Rule()
						r_list = line.split()
						if len(r_list) < 4:
							err("Rule found with fewer than 4 columns")
							continue
						this_rule.keyword =	True if int(r_list[0]) > 0 else False
						this_rule.abbrev = r_list[1].replace("_", " ")
						this_rule.category = r_list[2]
						this_rule.score = int(r_list[3])

						if len(r_list) > 4:
							this_rule.full = r_list[4].replace("_", " ")
						rule_list.append(this_rule)
	return rule_list;

#HTTP DOWNLOAD AND PARSE
def download_file(a_id, product):
	url = ""
	if product == "notams":
		post_r = {
				"Langue": "anglais", 
				"TypeBrief": "N",
				"NoSession": "17058462",
				"Stations": a_id, 
				"Location": "",
				"ni_File": "on",
				"ni_FIR": "on"
				}
		url = 'https://flightplanning.navcanada.ca/cgi-bin/Fore-obs/notam.cgi'
		r = requests.post(url, data=post_r)
	elif product == "weather":
		post_r = {
			"format" : "raw",
			"Langue" : "anglais",
			"Location" : "",
			"NoSession" : "NS_Inconnu",
			"Region" : "can",
			"Stations" : a_id
		}
		url = 'https://flightplanning.navcanada.ca/cgi-bin/Fore-obs/metar.cgi'	
		r = requests.post(url, data=post_r)
	html = r.text
	return html

#Returns a list of raw notams, un-parsed
def find_notams(html):
	#remove newlines to make the following regex work correctly
	html = html.replace("\n", "*")
	#Find &nbsp; followed by 6 digits (time stamp) and finished by </pre
	raw_list = re.findall('&nbsp;(\d{6}.*?)<\/pre', html)
	return raw_list;

def find_weather_lines(html):
	html = html.replace("\n", "*")
	raw_list = re.findall('\*(?:TAF|SPECI|METAR).*?=', html)
	return raw_list;

def z_to_l(z_dt):
	return z_dt.replace(tzinfo=timezone.utc).astimezone(tz=None)


def parse_wx(raw_wx, tz_diff):
	wxtype = ""
	origin_code = None
	raw_issue_time_l = None

	text = ""
	m_or_s = False
	raw_wx = raw_wx[1:] #strip preceding *
	raw_wx = raw_wx.replace("<br>", "")

	#METAR/SPECI
	if raw_wx[0:5] == 'METAR' or raw_wx[0:4] == 'SPECI':
		wxtype = raw_wx
		results = raw_wx.split()
		origin_code = results[1]
		x = 0
		for word in results:
			if len(word) == 7 and word[0:6].isdigit(): #051600Z
				results[x] = wx_time_local(word[0:6], tz_diff)
			x += 1
		text = ' '.join(results)

	elif raw_wx[0:3] == 'TAF':
		wxtype = 'TAF'
		raw_wx = raw_wx.replace("*", "")
		results = raw_wx.split()
		x = 0
		for word in results:
			if origin_code is None and len(word) == 4:
				origin_code = word
			elif re.match("FM\d{6}", word) is not None: #FM052000
				results[x] = "<br>" + "FM" + wx_time_local(word[2:8], tz_diff)
			elif word == 'TEMPO':
				results[x] = "<br>&nbsp;&nbsp;" + word
			elif word == 'RMK':
				results[x] = "<br>" + word
			elif word == 'BECMG':
				results[x] = "<br>" + word
			elif (len(word) == 7 or len(word) == 8) and word[0:6].isdigit(): #051600Z[=]
				results[x] = wx_time_local(word[0:6], tz_diff)
			elif re.match("\d{4}/\d{4}", word): #0210/0218
				results[x] = wx_time_local(word[0:4], tz_diff) + "/" + wx_time_local(word[5:9], tz_diff)
			#elif raw_issue_time is None and len(word) == 6 and word.isdigit():
			#	raw_issue_time = word
			x += 1
		text = Markup(' '.join(results))
	#text = text.replace("*", "")
	text = text.lower()
	return Wx(origin_code, text)


def parse_notam(raw_notam):
	raw_issue_time = None
	raw_from_time = None
	raw_till_time = None
	origin_code = ""
	origin_name = ""
	text = ""

	#Get the time block first because it changes the way we collect the text
	date_match2 = re.search("(\d{10}?).*\d{10}\*$", raw_notam) #match if there's a FROM date found
	date_match = re.search("(\d{10})\*$", raw_notam) #match the TILL date

	#if the above line found both a FROM and a TILL date
	if date_match2 is not None:
		raw_from_time = str(date_match2.group(1)) #take the FROM part
	if date_match is not None:
		raw_till_time = str(date_match.group(1))

	#Now do the rest
	#there's no TIL date 
	if raw_till_time is None:
		parse_match = re.match("(\d{6}) (\w{4}) (.*?)\*(.*)",raw_notam)
	else: #there is a TIL date, eat the date/time blocks at the end
		parse_match = re.match("(\d{6}) (\w{4}) (.*?)\*(.*?)\d{10}",raw_notam)

	if parse_match[1]:
		raw_issue_time = parse_match.group(1).replace("*", " ")
	if parse_match[2]:
		origin_code = parse_match.group(2).replace("*", " ")
	if parse_match[3]:
		origin_name = parse_match.group(3).replace("*", " ")
		origin_name = origin_name.title()
		if re.search(" Fir$", origin_name) is not None:
			origin_code = origin_code + "-FIR"
	if parse_match[4]:
		text = " " + parse_match.group(4).replace("*", " ")

	n = Notam(origin_code, origin_name, parse_time(raw_issue_time), parse_time(raw_from_time), parse_time(raw_till_time), text)
	return n;

def wx_time_local(t, tz_diff):
	if tz_diff == 0:
		return t + "Z"
	TZ_DIFF = tz_diff
	today = "L"
	tomorrow = "TMRW"
	yesterday = "YSDY"
	two_days_ago = "2DYSAGO"

	
	now = datetime.datetime.now()
	if t is None or int(t) == 0:
		return None;
	if t.isdigit():
		if len(t) >= 4:
			minute = 0
			day = int(t[0:2])
			hour = int(t[2:4])
		if len(t) >= 6:
				minute = int(t[4:6])
	str_today = ""
	#ex: 0200 Z tomorrow -5TZ
	# (24+ (2-5)) = 2200Z yesterday
	if hour+TZ_DIFF <= 0: #roll back the day by one (avoid caledar stuff by saying 'yesterday')
		if day > now.day: #time given is showing as tomorrow, but is today local
			str_today = today
			hour = 24+(hour+TZ_DIFF)
		elif day == now.day: #time given is showing today, but is actualy yesterday local
			str_today = yesterday
			hour = 24+(hour+TZ_DIFF)
		elif day < now.day: #time tdygiven shows yesterday, 
			str_today = two_days_ago
			hour = 24+(hour+TZ_DIFF)
	else:
		hour = hour+TZ_DIFF
		if day == now.day+1:
			str_today = tomorrow
		elif day == now.day-1:
			str_today = yesterday
		elif day == now.day:
			str_today = today

	return '{:02d}{:02d}{}'.format(int(hour),int(minute),str_today)

#Returns a datetime object from a given 6 or 10 digit string
def parse_time(d):
	if d is None or int(d) == 0: #000000
		return None;
	if d.isdigit():
		year = 2000 + int(d[0:2])
		month = int(d[2:4])
		if month > 12 or month < 1:
			err("Attempted to parse a date with invalid month")
			return None;
		day = int(d[4:6])
		if day > 31 or day < 1:
			err("Attempted to parse a date with invalid day")
			return None;
		hour = 0
		minute = 0
		if len(d) == 10: #10 digit date/time string
			hour = int(d[6:8])
			minute = int(d[8:10])
		#pump that time info into a naive datetime object
		return datetime.datetime(year,month,day,hour,minute)
	else:
		err("Something other than a digit tried to be converted to a date: " + d)
		return None

def err(e):
	global g_error_str
	g_error_str = g_error_str + "\n" + e
	return


def date_to_casual(d):
	if d is None: return None
	rstr = ""
	today = datetime.datetime.utcnow()
	delta = d - today

	#return only close days
	if abs(delta.days) > 10:
		return ""

	if delta.days == 1:
		return "(" + str(abs(int(round(delta.seconds/(60*60))))) + " hours from now)"
	elif delta.days == -1:
		return "(" + str(abs(int(round(delta.seconds/(60*60))))) + " hours ago)"
	else:
		rstr = "(" + str(abs(delta.days)) + " days"

	if delta.days > 0:
		rstr = rstr + " from now)"
	elif delta.days < 0:
		rstr = rstr + " ago)"
	else: #today
		rstr = rstr + "(today)"
	return rstr

def date_to_str(dt):
	if dt is None: return None
	if dt.hour:
		return dt.strftime("%d %b %y @ %H:%M Z")
	else:
		return dt.strftime("%d %b %y")
