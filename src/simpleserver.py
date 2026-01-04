#!/usr/bin/env python

"""Simple HTTP Server With Upload.

This module builds on BaseHTTPServer by implementing the standard GET
and HEAD requests in a fairly straightforward manner.

"""


__version__ = "0.2"
__all__ = ["SimpleHTTPRequestHandler"]
__author__ = "gil"
__home_page__ = "http://adrianogil.github.io"

import os
import posixpath
import urllib
import cgi
import html
import shutil
import mimetypes
import re
from io import BytesIO

from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import threading
import sys, zipfile


def sizeof_fmt(num, suffix='B'):
    for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)


class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

    """Simple HTTP request handler with GET/HEAD/POST commands.

    This serves files from the current directory and any of its
    subdirectories.  The MIME type for files is determined by
    calling the .guess_type() method. And can reveive file uploaded
    by client.

    The GET/HEAD/POST requests are identical except that the HEAD
    request omits the actual contents of the file.

    """

    server_version = "SimpleHTTPWithUpload/" + __version__

    def do_GET(self):
        """Serve a GET request."""
        f = self.send_head()
        if f:
            self.copyfile(f, self.wfile)
            f.close()

    def do_HEAD(self):
        """Serve a HEAD request."""
        f = self.send_head()
        if f:
            f.close()

    def do_POST(self):
        """Serve a POST request."""
        r, info = self.deal_post_data()
        print(r, info, "by: ", self.client_address)
        f = BytesIO()

        def customwrite(htmlstring):
            f.write(htmlstring.encode('utf-8'))

        customwrite("<!DOCTYPE html>\n")
        customwrite("<html lang=\"en\">\n")
        customwrite("<head>\n")
        customwrite("<meta charset=\"utf-8\">\n")
        customwrite("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n")
        customwrite("<title>Upload Result</title>\n")
        customwrite("<style>\n")
        customwrite("body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;"
                    "background:#f5f7fb;color:#1f2937;margin:0;padding:32px;}\n")
        customwrite(".card{max-width:720px;margin:0 auto;background:#fff;border-radius:14px;"
                    "box-shadow:0 10px 30px rgba(15,23,42,.08);padding:28px;}\n")
        customwrite(".title{font-size:22px;margin:0 0 8px;}\n")
        customwrite(".status{font-weight:600;margin:12px 0;}\n")
        customwrite(".status.success{color:#059669;}\n")
        customwrite(".status.fail{color:#dc2626;}\n")
        customwrite(".actions a{display:inline-block;margin-top:12px;padding:8px 14px;"
                    "background:#2563eb;color:#fff;border-radius:8px;text-decoration:none;}\n")
        customwrite(".footer{margin-top:18px;font-size:12px;color:#64748b;}\n")
        customwrite("</style>\n")
        customwrite("</head>\n")
        customwrite("<body>\n")
        customwrite("<div class=\"card\">\n")
        customwrite("<h2 class=\"title\">Upload Result</h2>\n")
        if r:
            customwrite("<div class=\"status success\">Success</div>\n")
        else:
            customwrite("<div class=\"status fail\">Failed</div>\n")
        customwrite("<p>%s</p>\n" % info)
        customwrite("<div class=\"actions\"><a href=\"%s\">Back to listing</a></div>\n" % self.headers['referer'])
        customwrite("<div class=\"footer\">Powered By: Gil, check new version at "
                    "<a href=\"https://github.com/adrianogil/simple-server\">here</a>.</div>\n")
        customwrite("</div>\n")
        customwrite("</body>\n</html>\n")
        length = f.tell()
        f.seek(0)
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if f:
            self.copyfile(f, self.wfile)
            f.close()

    def create_directory(self, path, folder_name, last_page):
        print("create_directory %s %s" % (path, folder_name))

        result = True

        new_folder = os.path.join(path, folder_name)

        if os.path.exists(new_folder):
            result = False
        else:
            os.mkdir(new_folder)

        """Serve a POST request."""
        f = BytesIO()

        def customwrite(htmlstring):
            f.write(htmlstring.encode('utf-8'))

        customwrite("<!DOCTYPE html>\n")
        customwrite("<html lang=\"en\">\n")
        customwrite("<head>\n")
        customwrite("<meta charset=\"utf-8\">\n")
        customwrite("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n")
        customwrite("<title>Folder Created</title>\n")
        customwrite("<style>\n")
        customwrite("body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;"
                    "background:#f5f7fb;color:#1f2937;margin:0;padding:32px;}\n")
        customwrite(".card{max-width:720px;margin:0 auto;background:#fff;border-radius:14px;"
                    "box-shadow:0 10px 30px rgba(15,23,42,.08);padding:28px;}\n")
        customwrite(".title{font-size:22px;margin:0 0 8px;}\n")
        customwrite(".status{font-weight:600;margin:12px 0;}\n")
        customwrite(".status.success{color:#059669;}\n")
        customwrite(".status.fail{color:#dc2626;}\n")
        customwrite(".actions a{display:inline-block;margin-top:12px;padding:8px 14px;"
                    "background:#2563eb;color:#fff;border-radius:8px;text-decoration:none;}\n")
        customwrite(".footer{margin-top:18px;font-size:12px;color:#64748b;}\n")
        customwrite("</style>\n")
        customwrite("</head>\n")
        customwrite("<body>\n")
        customwrite("<div class=\"card\">\n")
        customwrite("<h2 class=\"title\">Folder \"%s\"</h2>\n" % folder_name)
        if result:
            customwrite("<div class=\"status success\">Created successfully.</div>\n")
        else:
            customwrite("<div class=\"status fail\">Folder already exists.</div>\n")
        customwrite("<div class=\"actions\"><a href=\"%s\">Back to listing</a></div>\n" % last_page)
        customwrite("<div class=\"footer\">Powered By: Gil, check new version at "
                    "<a href=\"https://github.com/adrianogil/simple-server\">here</a>.</div>\n")
        customwrite("</div>\n")
        customwrite("</body>\n</html>\n")
        length = f.tell()
        f.seek(0)
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if f:
            self.copyfile(f, self.wfile)
            f.close()

    def delete_file(self, path, file_name, last_page):
        print("delete_file %s %s" % (path, file_name))

        result = True

        file_path = os.path.join(path, file_name)

        if os.path.exists(file_path):
            os.remove(file_path)

        """Serve a POST request."""
        f = BytesIO()

        def customwrite(htmlstring):
            f.write(htmlstring.encode('utf-8'))

        customwrite("<!DOCTYPE html>\n")
        customwrite("<html lang=\"en\">\n")
        customwrite("<head>\n")
        customwrite("<meta charset=\"utf-8\">\n")
        customwrite("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n")
        customwrite("<title>File Removed</title>\n")
        customwrite("<style>\n")
        customwrite("body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;"
                    "background:#f5f7fb;color:#1f2937;margin:0;padding:32px;}\n")
        customwrite(".card{max-width:720px;margin:0 auto;background:#fff;border-radius:14px;"
                    "box-shadow:0 10px 30px rgba(15,23,42,.08);padding:28px;}\n")
        customwrite(".title{font-size:22px;margin:0 0 8px;}\n")
        customwrite(".status{font-weight:600;margin:12px 0;}\n")
        customwrite(".status.success{color:#059669;}\n")
        customwrite(".status.fail{color:#dc2626;}\n")
        customwrite(".actions a{display:inline-block;margin-top:12px;padding:8px 14px;"
                    "background:#2563eb;color:#fff;border-radius:8px;text-decoration:none;}\n")
        customwrite(".footer{margin-top:18px;font-size:12px;color:#64748b;}\n")
        customwrite("</style>\n")
        customwrite("</head>\n")
        customwrite("<body>\n")
        customwrite("<div class=\"card\">\n")
        customwrite("<h2 class=\"title\">Removed \"%s\"</h2>\n" % file_name)
        if result:
            customwrite("<div class=\"status success\">File deleted successfully.</div>\n")
        else:
            customwrite("<div class=\"status fail\">Failed to delete file.</div>\n")
        customwrite("<div class=\"actions\"><a href=\"%s\">Back to listing</a></div>\n" % last_page)
        customwrite("<div class=\"footer\">Powered By: Gil, check new version at "
                    "<a href=\"https://github.com/adrianogil/simple-server\">here</a>.</div>\n")
        customwrite("</div>\n")
        customwrite("</body>\n</html>\n")
        length = f.tell()
        f.seek(0)
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if f:
            self.copyfile(f, self.wfile)
            f.close()

    def deal_post_data(self):
        ctype, pdict = cgi.parse_header(self.headers['Content-Type'])
        pdict['boundary'] = bytes(pdict['boundary'], "utf-8")
        pdict['CONTENT-LENGTH'] = int(self.headers['Content-Length'])
        if ctype == 'multipart/form-data':
            form = cgi.FieldStorage( fp=self.rfile, headers=self.headers, environ={'REQUEST_METHOD':'POST', 'CONTENT_TYPE':self.headers['Content-Type'], })
            print (type(form))
            try:
                if isinstance(form["file"], list):
                    for record in form["file"]:
                        open("./%s"%record.filename, "wb").write(record.file.read())
                else:
                    print(form["file"].filename)
                    open("./%s"%form["file"].filename, "wb").write(form["file"].file.read())
            except IOError:
                    return (False, "Can't create file to write, do you have permission to write?")
        return (True, "Files uploaded")

    def send_head(self):
        """Common code for GET and HEAD commands.

        This sends the response code and MIME headers.

        Return value is either a file object (which has to be copied
        to the outputfile by the caller unless the command was HEAD,
        and must be closed by the caller under all circumstances), or
        None, in which case the caller has nothing further to do.

        """
        path = self.translate_path(self.path)
        print("send_head - path: " + str(self.path))
        f = None
        if '?deletefile=' in self.path:
            index = self.path.index('?deletefile=')
            file_to_be_deleted = self.path[index + 12:]
            print("Let's delete file: " + file_to_be_deleted)
            return self.delete_file(path, file_to_be_deleted, self.path[:index])
        elif '?createfolder=' in self.path:
            index = self.path.index('?createfolder=')
            folder_name = self.path[index + 14:]
            return self.create_directory(path, folder_name, self.path[:index])
        elif self.path.endswith('?download'):
            tmp_file = "tmp.zip"
            self.path = self.path.replace("?download","")

            # Improve zipped path
            zip = zipfile.ZipFile(tmp_file, 'w')
            for root, dirs, files in os.walk(path):
                for file in files:
                    if os.path.join(root, file) != os.path.join(root, tmp_file):
                        zip.write(os.path.join(root, file))
            zip.close()
            path = self.translate_path(tmp_file)
        elif os.path.isdir(path):
            if not self.path.endswith('/'):
                # redirect browser - doing basically what apache does
                self.send_response(301)
                self.send_header("Location", self.path + "/")
                self.end_headers()
                return None
            for index in "index.html", "index.htm":
                index = os.path.join(path, index)
                if os.path.exists(index):
                    path = index
                    break
            else:
                return self.list_directory(path)
        ctype = self.guess_type(path)
        try:
            # Always read in binary mode. Opening files in text mode may cause
            # newline translations, making the actual size of the content
            # transmitted *less* than the content-length!
            f = open(path, 'rb')
        except IOError:
            self.send_error(404, "File not found")
            return None
        self.send_response(200)
        self.send_header("Content-type", ctype)
        fs = os.fstat(f.fileno())
        self.send_header("Content-Length", str(fs[6]))
        self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
        self.end_headers()
        return f

    def list_directory(self, path):
        """Helper to produce a directory listing (absent index.html).

        Return value is either a file object, or None (indicating an
        error).  In either case, the headers are sent, making the
        interface the same as for send_head().

        """
        try:
            list = os.listdir(path)
        except os.error:
            self.send_error(404, "No permission to list directory")
            return None
        list.sort(key=lambda a: a.lower())
        f = BytesIO()
        displaypath = html.escape(urllib.parse.unquote(self.path))

        js_action_create_folder = "window.open('%s' + document.getElementById('folderName').value,'_self')" % (
                self.path.strip() + "?createfolder=",
            )

        def customwrite(htmlstring):
            f.write(htmlstring.encode('utf-8'))

        customwrite("<!DOCTYPE html>\n")
        customwrite("<html lang=\"en\">\n")
        customwrite("<head>\n")
        customwrite("<meta charset=\"utf-8\">\n")
        customwrite("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n")
        customwrite("<title>Directory listing for %s</title>\n" % displaypath)
        customwrite("<style>\n")
        customwrite("body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;"
                    "background:#f5f7fb;color:#0f172a;margin:0;padding:32px;}\n")
        customwrite(".container{max-width:960px;margin:0 auto;}\n")
        customwrite(".card{background:#fff;border-radius:16px;padding:24px;"
                    "box-shadow:0 12px 30px rgba(15,23,42,.08);}\n")
        customwrite(".header{display:flex;flex-direction:column;gap:6px;margin-bottom:18px;}\n")
        customwrite(".header h2{margin:0;font-size:24px;}\n")
        customwrite(".header .path{color:#64748b;font-size:14px;}\n")
        customwrite(".actions{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:18px;}\n")
        customwrite(".actions form{display:flex;align-items:center;gap:8px;"
                    "background:#f8fafc;padding:10px 12px;border-radius:12px;"
                    "border:1px solid #e2e8f0;}\n")
        customwrite("input[type='text'],input[type='file']{font-size:14px;}\n")
        customwrite(".btn{background:#2563eb;color:#fff;border:none;border-radius:8px;"
                    "padding:8px 12px;font-size:14px;cursor:pointer;}\n")
        customwrite(".btn.secondary{background:#0f172a;}\n")
        customwrite(".list{list-style:none;margin:0;padding:0;}\n")
        customwrite(".list li{display:flex;align-items:center;justify-content:space-between;"
                    "padding:10px 12px;border-bottom:1px solid #eef2f7;}\n")
        customwrite(".list li:last-child{border-bottom:none;}\n")
        customwrite(".file-link{color:#1d4ed8;text-decoration:none;font-weight:500;}\n")
        customwrite(".file-meta{display:flex;align-items:center;gap:12px;color:#64748b;font-size:12px;}\n")
        customwrite(".delete{background:#ef4444;color:#fff;border-radius:8px;text-decoration:none;"
                    "padding:4px 8px;font-size:12px;}\n")
        customwrite(".footer{margin-top:20px;font-size:12px;color:#64748b;}\n")
        customwrite("</style>\n")
        customwrite("</head>\n")
        customwrite("<body>\n")
        customwrite("<div class=\"container\">\n")
        customwrite("<div class=\"card\">\n")
        customwrite("<div class=\"header\">\n")
        customwrite("<h2>Directory listing</h2>\n")
        customwrite("<div class=\"path\">%s</div>\n" % displaypath)
        customwrite("</div>\n")
        customwrite("<div class=\"actions\">\n")
        customwrite("<form ENCTYPE=\"multipart/form-data\" method=\"post\">")
        customwrite("<input name=\"file\" type=\"file\"/>")
        customwrite("<button class=\"btn\" type=\"submit\">Upload</button></form>\n")
        customwrite("<form ENCTYPE=\"multipart/form-data\">")
        customwrite("<label for=\"folderName\"><small>Create folder:</small></label>")
        customwrite("<input type=\"text\" id=\"folderName\" placeholder=\"New folder\">")
        customwrite("<button class=\"btn secondary\" type=\"button\" onclick=\"" + js_action_create_folder + "\">Create</button>")
        customwrite("</form>\n")
        customwrite("<a class=\"btn\" href='%s'>Download zip</a>\n" % (self.path + "?download",))
        customwrite("</div>\n")
        customwrite("<ul class=\"list\">\n")
        if self.path != "/":
            customwrite('<li><a href="%s">..</a>\n' % (urllib.parse.quote(self.path + ".."),))
        for name in list:
            fullname = os.path.join(path, name)
            displayname = linkname = name
            # Append / for directories or @ for symbolic links

            size_display = ""

            if os.path.isdir(fullname):
                displayname = name + "/"
                linkname = name + "/"
            else:
                size_value = os.path.getsize(fullname)
                size_value = sizeof_fmt(size_value)

                size_display = "<span>(%s)</span>" % (size_value,)

            if os.path.islink(fullname):
                displayname = name + "@"
                # Note: a link to a directory displays with @ and links with /
            customwrite("<li>")
            customwrite("<a class=\"file-link\" href=\"%s\">%s</a>" % (
                urllib.parse.quote(linkname),
                html.escape(displayname),
            ))
            customwrite("<div class=\"file-meta\">%s" % size_display)
            customwrite("<a class=\"delete\" href=\"%s\">Delete</a>" % (
                "?deletefile=" + html.escape(displayname),
            ))
            customwrite("</div></li>\n")
        customwrite("</ul>\n")
        customwrite("<div class=\"footer\">Powered By: Gil, check new version ")
        customwrite("<a href=\"https://github.com/adrianogil/simple-server\">")
        customwrite("here</a>.</div>\n")
        customwrite("</div>\n</div>\n</body>\n</html>\n")
        length = f.tell()
        f.seek(0)
        self.send_response(200)
        encoding = sys.getfilesystemencoding()
        self.send_header("Content-type", "text/html; charset=%s" % encoding)
        self.send_header("Content-Length", str(length))
        self.end_headers()
        return f

    def translate_path(self, path):
        """Translate a /-separated PATH to the local filename syntax.

        Components that mean special things to the local file system
        (e.g. drive or directory names) are ignored.  (XXX They should
        probably be diagnosed.)

        """
        # abandon query parameters
        path = path.split('?',1)[0]
        path = path.split('#',1)[0]
        path = posixpath.normpath(urllib.parse.unquote(path))
        words = path.split('/')
        words = filter(None, words)
        path = os.getcwd()
        for word in words:
            drive, word = os.path.splitdrive(word)
            head, word = os.path.split(word)
            if word in (os.curdir, os.pardir): continue
            path = os.path.join(path, word)
        return path

    def copyfile(self, source, outputfile):
        """Copy all data between two file objects.

        The SOURCE argument is a file object open for reading
        (or anything with a read() method) and the DESTINATION
        argument is a file object open for writing (or
        anything with a write() method).

        The only reason for overriding this would be to change
        the block size or perhaps to replace newlines by CRLF
        -- note however that this the default server uses this
        to copy binary data as well.

        """
        shutil.copyfileobj(source, outputfile)

    def guess_type(self, path):
        """Guess the type of a file.

        Argument is a PATH (a filename).

        Return value is a string of the form type/subtype,
        usable for a MIME Content-type header.

        The default implementation looks the file's extension
        up in the table self.extensions_map, using application/octet-stream
        as a default; however it would be permissible (if
        slow) to look inside the data to make a better guess.

        """

        base, ext = posixpath.splitext(path)
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        ext = ext.lower()
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        else:
            return self.extensions_map['']

    if not mimetypes.inited:
        mimetypes.init() # try to read system mime.types
    extensions_map = mimetypes.types_map.copy()
    extensions_map.update({
        '': 'application/octet-stream', # Default
        '.py': 'text/plain',
        '.c': 'text/plain',
        '.h': 'text/plain',
        })

try:
    # Python 2.x
    from SocketServer import ThreadingMixIn
    from http.server import HTTPServer
except ImportError:
    # Python 3.x
    from socketserver import ThreadingMixIn
    from http.server import HTTPServer

class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    pass

if sys.argv[1:]:
    address = sys.argv[1]
    if (':' in address):
        interface = address.split(':')[0]
        port = int(address.split(':')[1])
    else:
        interface = '0.0.0.0'
        port = int(address)
else:
    port = 8000
    interface = '0.0.0.0'

if sys.argv[2:]:
    os.chdir(sys.argv[2])

print('Started HTTP server on ' +  interface + ':' + str(port))


def run_server():
    server = ThreadingSimpleServer((interface, port), SimpleHTTPRequestHandler)
    try:
        while 1:
            sys.stdout.flush()
            server.handle_request()
    except KeyboardInterrupt:
        print('Finished.')

if __name__ == '__main__':
    run_server()
