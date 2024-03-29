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

        customwrite('<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">')
        customwrite("<html>\n<title>Upload Result Page</title>\n")
        customwrite("<body>\n<h2>Upload Result Page</h2>\n")
        customwrite("<hr>\n")
        if r:
            customwrite("<strong>Success:</strong>")
        else:
            customwrite("<strong>Failed:</strong>")
        customwrite(info)
        customwrite("<br><a href=\"%s\">back</a>" % self.headers['referer'])
        customwrite("<hr><small>Powered By: Gil, check new version at ")
        customwrite("<a href=\"https://github.com/adrianogil/simple-server\">")
        customwrite("here</a>.</small></body>\n</html>\n")
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
        customwrite(b'<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">')
        customwrite(b"<html>\n<title>Folder Created Page</title>\n")
        customwrite(b"<body>\n<h2>Folder \"%s\" Create Page</h2>\n" % (folder_name,))
        customwrite(b"<hr>\n")
        if result:
            customwrite(b"<strong>Success:</strong>")
        else:
            customwrite(b"<strong>Failed. Folder already exists!:</strong>")
        customwrite(b"<br><a href=\"%s\">back</a>" % (last_page,))
        customwrite(b"<hr><small>Powered By: Gil, check new version at ")
        customwrite(b"<a href=\"https://github.com/adrianogil/simple-server\">")
        customwrite(b"here</a>.</small></body>\n</html>\n")
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
        customwrite(b'<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">')
        customwrite(b"<html>\n<title>File removed </title>\n")
        customwrite(b"<body>\n<h2>File \"%s\" was removed!</h2>\n(No backup had been made /o\\)" % (file_name,))
        customwrite(b"<hr>\n")
        if result:
            customwrite(b"<strong>Success:</strong>")
        else:
            customwrite(b"<strong>Failed because of reasons!:</strong>")
        customwrite(b"<br><a href=\"%s\">back</a>" % (last_page,))
        customwrite(b"<hr><small>Powered By: Gil, check new version: ")
        customwrite(b"<a href=\"https://github.com/adrianogil/simple-server\">")
        customwrite(b"here</a>.</small></body>\n</html>\n")
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

        customwrite('<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">')
        customwrite("<html>\n<title>Directory listing for %s</title>\n" % displaypath)
        customwrite("<body>\n<h2>Directory listing for %s</h2>\n" % displaypath)
        customwrite("<hr>\n")
        customwrite("<form ENCTYPE=\"multipart/form-data\" method=\"post\">")
        customwrite("<input name=\"file\" type=\"file\"/>")
        customwrite("<input type=\"submit\" value=\"upload\"/></form>\n")
        customwrite("<form ENCTYPE=\"multipart/form-data\">")
        customwrite("<small><i>Create folder:</i></small> <input type=\"text\" id=\"folderName\">")
        customwrite("<input type=\"button\" value=\"Create\" onclick=\"" + js_action_create_folder + "\">")
        customwrite("</form>\n")
        customwrite("<hr>\n<ul>\n")
        customwrite("<a href='%s'>%s</a>\n" % (self.path+"?download",'Download Directory Tree as Zip'))
        customwrite("<hr>\n<ul>\n")
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

                size_display = "   <small><i>(%s)</i></small>" % (size_value,)

            if os.path.islink(fullname):
                displayname = name + "@"
                # Note: a link to a directory displays with @ and links with /
            customwrite('<li><a href="%s">%s</a>%s <a style="background-color: #FF4500; color: #ffffff; text-decoration: none; text-align: center; height: 10px; width: 30px; padding: 2px 2px; border-top-left-radius: 3px; border-top-right-radius: 3px; border-bottom-left-radius: 3px; border-bottom-right-radius: 3px;" href="%s">x</a>\n'
                    % (urllib.parse.quote(linkname), html.escape(displayname), size_display, '?deletefile=' + html.escape(displayname)))
        customwrite("</ul></ul>\n\n")
        customwrite("<hr><small>Powered By: Gil, check new version ")
        customwrite("<a href=\"https://github.com/adrianogil/simple-server\">")
        customwrite("here</a>.</small></body>\n</html>\n")
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
