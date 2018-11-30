# . venv/bin/activate
# export FLASK_APP=notams.py
# export FLASK_DEBUG=1
# flask run

from flask import Flask
import requests
import re
import datetime
import sys

app = Flask(__name__)
g_error_str = ""
# List order:
#  Notam File
#		Category
#			Score
#

class Notam:
	origin_code = ""
	origin_name = ""
	text = ""

	dt_issue_time = None
	dt_from_time = None
	dt_till_time = None
	recent = False
	date_score = 0
	
	score = 0 
	tags = None 
	
	def __init__(self, origin_code, origin_name, dt_issue_time, dt_from_time, dt_till_time, text):
		self.origin_code = origin_code
		self.origin_name = origin_name
		if dt_issue_time: self.dt_issue_time = dt_issue_time
		if dt_from_time: self.dt_from_time = dt_from_time
		if dt_till_time: self.dt_till_time = dt_till_time
		self.text = text
		tags = [] #list of strings

class Rule:
	abbrev = ""
	keyword = False #search for abbrev in text to apply rule
	score = 0
	full = ""
	category = ""


@app.route('/')
def main():
	notams = []
	html = download_file("CYTR")
	raw_list = find_notams(html)

	rule_list = load_rules("static/rules2")
	
	for raw_notam in raw_list:
		n = parse_notam(raw_notam)
		notams.append(n)
		apply_rules(n, rule_list)
	
	return 'Hello from Flask!' + str(len(html))

def apply_rules(n, rule_list):
	score_on_dates(n)
	n.score += n.date_score
	kw_found = False #can only be scored on one keyword
	for r in rule_list:
		if r.keyword is True:
			if re.search("\s" + r.abbrev + "\W", n.text) is not None:	
				if kw_found == False: #no keywords found yet
					n.score += r.r_score #score on this keyword
					n.tags.append(n.abbrev)
					if r.category > 0:
						n.category = r.category
						kw_found = True
				if r.replace:
						n.text = n.text.replace(r.abbrev, r.r_full)
		elif r.abbrev == "VICTORS":
			if kw_found == True:
				continue
			if re.search("V\d{2}", n.text) is not None:
				n.score += r.r_score
				n.category = r.category
				add_to_log(n, r.abbrev, r.r_score)
				kw_found = True



def load_rules(filename):
	#f = open(filename, "r")
	with app.open_resource('rules') as f:
		rule_list = []
		for line in f:
			 if line:
				 line = line.decode('UTF-8') #because open_resource apparently spits out bytes
				 if line[0:1] == "#" or len(line) < 5:
					 continue
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


def download_file(a_id):
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
	html = r.text
	return html

#Returns a list of raw notams, un-parsed
def find_notams(html):
	#remove newlines to make the following regex work correctly
	html = html.replace("\n", "*")
	#Find &nbsp; followed by 6 digits (time stamp) and finished by </pre
	raw_list = re.findall('&nbsp;(\d{6}.*?)<\/pre', html)
	return raw_list;
  
def parse_notam(raw_notam):
	raw_issue_time = None
	raw_from_time = None
	raw_till_time = None
	origin_code = ""
	origin_name = ""
	text = ""

	#Get the time block first because it changes the way we collect the text
	date_match2 = re.search("(\d{10}?).*\d{10}\*$", raw_notam) #match if there's a FROM date found

	#if there's a FROM and a TILL date found	
	if date_match2 is not None:
		raw_from_time = str(date_match2.group(1))
	else: #no FROM and TILL found
		date_match = re.search("(\d{10})\*$", raw_notam) #match the TILL date
		if date_match is not None: #only a TILL date found
			raw_till_time = str(date_match.group(1))
	
	#Now do the rest
	#there's no TIL date 
	if raw_till_time is None:
		parse_match = re.match("(\d{6}) (\D{4}) (.*?)\*(.*)",raw_notam)
	else: #there is a TIL date, eat the date/time blocks at the end
		parse_match = re.match("(\d{6}) (\D{4}) (.*?)\*(.*?)\d{10}",raw_notam)
	
	if parse_match[1]:
		raw_issue_time = parse_match.group(1).replace("*", " ")
	if parse_match[2]:
		origin_code = parse_match.group(2).replace("*", " ")
	if parse_match[3]:
		origin_name = parse_match.group(3).replace("*", " ")
	if parse_match[4]:
		text = " " + parse_match.group(4).replace("*", " ")
	
	n = Notam(origin_code, origin_name, parse_time(raw_issue_time), parse_time(raw_from_time), parse_time(raw_till_time), text)
	return n;

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

