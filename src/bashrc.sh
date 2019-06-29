# @tool simple-http-server
alias shttp-server-simple='python2 -m SimpleHTTPServer'
# Improved HTTP Server with upload and directory download
# Based on https://gist.github.com/UniIsland/3346170#file-simplehttpserverwithupload-py
# Based on https://stackoverflow.com/questions/2573670/download-whole-directories-in-python-simplehttpserver
# Simple HTTP Server
function shttp-server()
{
    if [ -z "$1" ]
    then
        port=8080
    else
        port=$1
    fi
    screen -S httpserver-$port -dm python2 $CONFIG_FILES_DIR/python/simpleserver/CustomHTTPServer.py $port
}

function shttp-server-rnd()
{
    port=$(rnd-port)
    screen -S httpserver-$port -dm python2 $CONFIG_FILES_DIR/python/simpleserver/CustomHTTPServer.py $port
}

function shttp-server-running()
{
    screen -list | grep httpserver | awk '{print $1}'
}