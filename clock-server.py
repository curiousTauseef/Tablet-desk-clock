# 
# Tablet desk clock
# 
# Copyright (c) 2016 Project Nayuki
# All rights reserved. Contact Nayuki for licensing.
# https://www.nayuki.io/page/tablet-desk-clock
# 
# Run this web server script with no arguments. For Python 3+.
# Open web browser and visit: http://localhost:51367/
# 


# ---- Prelude ----

import sys
if sys.version_info[ : 3] < (3, 0, 0):
	raise RuntimeError("Requires Python 3+")
import bottle, datetime, json, os, random, re, socket, sqlite3, struct, threading, time, urllib.request, xml.etree.ElementTree


# ---- Static file serving ----

web_root_dir = "web"
authorized_static_files = set()

@bottle.route("/")
def index():
	bottle.redirect("clock.html", 301)

@bottle.route("/<path:path>")
def static_file(path):
	if path not in authorized_static_files:
		authorized_static_files.clear()
		scan_static_files(web_root_dir, "")
	if path in authorized_static_files:
		mime = "auto"
		for ext in MIME_TYPES:
			if path.endswith("." + ext):
				mime = MIME_TYPES[ext]
				break
		return bottle.static_file(path, root=web_root_dir, mimetype=mime)
	else:
		bottle.abort(404)

MIME_TYPES = {"html":"application/xhtml+xml", "svg":"image/svg+xml", "ttf":"application/x-font-ttf"}

def scan_static_files(fspath, webpath):
	if os.path.isfile(fspath):
		authorized_static_files.add(webpath)
	elif os.path.isdir(fspath):
		if webpath != "":
			webpath += "/"
		for name in os.listdir(fspath):
			scan_static_files(os.path.join(fspath, name), webpath + name)


# ---- Clock module ----

# Yields the time source and current Unix millisecond time, e.g.: ["server", 1433185355946] or ["ntp", 1470939694075].
@bottle.route("/get-time.json")
def gettime():
	bottle.response.content_type = "application/json"
	bottle.response.set_header("Cache-Control", "no-cache")
	
	sock = None
	try:  # Try to get time from NTP
		target = socket.getaddrinfo("ca.pool.ntp.org", 123)[0][4]
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		sock.bind(("0.0.0.0", 0))
		sock.settimeout(1.0)
		
		startclock = time.time()
		sock.sendto(bytes([0x1B] + [0] * 47), target)
		packet = sock.recv(100)
		endclock = time.time()
		
		fields = struct.unpack(">BBBBIIIQQQQ", packet)
		header = fields[0]
		leap = header >> 6
		version = (header >> 3) & 7
		mode = header & 7
		if leap == 3 or version != 3 or mode != 4:
			raise ValueError("Response contains invalid data")
		receivetime = fields[9]
		transmittime = fields[10]
		
		elapsedclock = endclock - startclock
		servermidpoint = (transmittime + receivetime) // 2
		correctedtime = (servermidpoint + int(elapsedclock / 2.0 * float(2**32))) * 1000 // 2**32 - 2208988800000
		return json.dumps(["ntp", correctedtime])
		
	except:  # Fall back to this web server's time
		return json.dumps(["server", round(time.time() * 1000)])
	finally:  # Clean up
		if sock is not None:
			sock.close()


# Yields {a random file name in the wallpapers directory} as a string or null if unavailable, e.g.: "sample2.png"
@bottle.route("/random-wallpaper.json")
def random_wallpaper():
	bottle.response.content_type = "application/json"
	bottle.response.set_header("Cache-Control", "no-cache")
	candidates = get_wallpaper_candidates()
	if len(candidates) == 0:
		return "null"
	else:
		return '"' + random.choice(candidates) + '"'


# Yields a file name or null, a wallpaper that changes only once a day (history kept on the server side).
@bottle.route("/get-wallpaper.json")
def get_wallpaper():
	bottle.response.content_type = "application/json"
	bottle.response.set_header("Cache-Control", "no-cache")
	candidates = set(get_wallpaper_candidates())
	if len(candidates) == 0:
		return "null"
	
	try:
		con = sqlite3.connect("wallpaper-history.sqlite")
		cur = con.cursor()
		cur.execute("CREATE TABLE IF NOT EXISTS wallpaper_history(date VARCHAR NOT NULL, filename VARCHAR NOT NULL)")
		con.commit()
		
		today = datetime.date.today().strftime("%Y%m%d")
		cur.execute("SELECT filename FROM wallpaper_history WHERE date=?", (today,))
		data = cur.fetchone()
		if data is not None:
			return '"' + data[0] + '"'
		
		cur.execute("SELECT date, filename FROM wallpaper_history ORDER BY date DESC")
		history = cur.fetchall()
		maxremove = min(round(len(candidates) * 0.67), len(candidates) - 3)
		for row in history[ : maxremove]:
			candidates.discard(row[1])
		maxhistory = 300
		if len(history) > maxhistory:
			cur.execute("DELETE FROM wallpaper_history WHERE date <= ?", (history[maxhistory][0],))
		result = random.choice(list(candidates))
		cur.execute("INSERT INTO wallpaper_history VALUES(?, ?)", (today, result))
		con.commit()
		return '"' + result + '"'
		
	finally:
		cur.close()
		con.close()


def get_wallpaper_candidates():
	dir = os.path.join(web_root_dir, "wallpaper")
	if not os.path.isdir(dir):
		return []
	cond = lambda name: os.path.isfile(os.path.join(dir, name)) and name.endswith((".jpg", ".png"))
	return [name for name in os.listdir(dir) if cond(name)]


@bottle.route("/network-status.json")
def network_status():
	result = []
	lock = threading.Lock()
	def append(x):
		lock.acquire()
		result.append(x)
		lock.release()
	threads = []
	
	def test_internet():
		for _ in range(3):
			host = random.choice(configuration["internet-test-web-sites"])
			try:
				sock = socket.create_connection((host, 80), timeout=1.0)
				sock.close()
				append(True)
				break
			except:
				pass
		else:
			append(False)
	th = threading.Thread(target=test_internet)
	threads.append(th)
	th.start()
	
	COMPUTER_TYPES = ("desktop", "laptop", "server")
	def test_computer(type, host, port):
		try:
			sock = socket.create_connection((host, port), timeout=1.0)
			sock.close()
			append(type)
		except:
			pass
	for comptype in COMPUTER_TYPES:
		for (host, port) in configuration["local-test-computers"][comptype]:
			th = threading.Thread(target=test_computer, args=(comptype,host,port))
			threads.append(th)
			th.start()
	
	for th in threads:
		th.join()
	def key_func(x):
		if type(x) is bool:
			return -1
		elif type(x) is str:
			return COMPUTER_TYPES.index(x)
		else:
			raise AssertionError()
	result.sort(key=key_func)
	
	bottle.response.content_type = "application/json"
	bottle.response.set_header("Cache-Control", "no-cache")
	return json.dumps(result)


# ---- Weather module ----

# Yields an object containing weather and sunrise data, e.g.:
# {"condition":"Mostly Cloudy", "temperature":"-2.5", "sunrise":"07:30", "sunset":"18:42"}
@bottle.route("/weather.json")
def weather():
	global weather_cache
	if weather_cache is None or time.time() > weather_cache[1]:
		# Data provided by Environment Canada. Documentation:
		# - http://dd.meteo.gc.ca/about_dd_apropos.txt
		# - http://dd.weather.gc.ca/citypage_weather/docs/README_citypage_weather.txt
		url = configuration["canada-weather-xml-url"]
		stream = urllib.request.urlopen(url=url, timeout=60)
		xmlstr = stream.read()
		stream.close()
		
		# Parse data and build result
		root = xml.etree.ElementTree.fromstring(xmlstr)
		result = {
			"condition"  : root.findtext("./currentConditions/condition"),
			"temperature": root.findtext("./currentConditions/temperature"),
		}
		for elem in root.findall("./riseSet/dateTime"):
			if elem.get("zone") != "UTC":
				s = elem.findtext("./hour") + ":" + elem.findtext("./minute")
				name = elem.get("name")
				if name in ("sunrise", "sunset"):
					result[name] = s
		
		# Expiration and caching
		now = time.time()
		expire = ((now - 3*60) // 3600 + 1) * 3600 + 3*60  # 3 minutes past the next hour
		expire = min(now + 20 * 60, expire)  # Or 20 minutes, whichever is earlier
		weather_cache = (json.dumps(result), expire)
	bottle.response.content_type = "application/json"
	bottle.response.set_header("Cache-Control", "no-cache")
	return weather_cache[0]

weather_cache = None  # Either None or a tuple of (JSON string, expiration time)


# ---- Morning module ----

# Stores or yields an object containing morning reminders, e.g.:
# {"20150531": ["Hello world", "Entry two"], "20150601": []}
@bottle.route("/morning-reminders.json", method=("GET","POST"))
def morning_reminders():
	if bottle.request.method == "GET":
		today = datetime.date.today()
		todelete = []
		for key in morning_reminders:
			d = datetime.date(int(key[0:4]), int(key[4:6]), int(key[6:8]))
			if not (0 <= (d - today).days <= 1):
				todelete.append(key)
		for key in todelete:
			del morning_reminders[key]
		bottle.response.content_type = "application/json"
		bottle.response.set_header("Cache-Control", "no-cache")
		return json.dumps(morning_reminders)
	elif bottle.request.method == "POST":
		data = bottle.request.body.read().decode("UTF-8")
		morning_reminders.update(json.loads(data))
		return "Success"

morning_reminders = {}


# ---- Server initialization ----

if __name__ == "__main__":
	with open("config.json", "r", encoding="UTF-8") as f:
		configuration = json.load(f)  # Global variable
	bottle.run(host="0.0.0.0", port=51367, reloader=True)
