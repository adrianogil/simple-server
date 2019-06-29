# @tool simple-http-server
alias simple-server-python='python2 -m SimpleHTTPServer'
# Improved HTTP Server with upload and directory download
# Based on https://gist.github.com/UniIsland/3346170#file-simplehttpserverwithupload-py
# Based on https://stackoverflow.com/questions/2573670/download-whole-directories-in-python-simplehttpserver
# Simple HTTP Server
function simple-server()
{
    if [ -z "$1" ]
    then
        port=8080
    else
        port=$1
    fi
    screen -S simpleserver-$port -dm python2 $SIMPLE_SERVER_DIR/simpleserver.py $port
}

function simple-server-rnd()
{
    port=$(rnd-port)
    screen -S simpleserver-$port -dm python2 $SIMPLE_SERVER_DIR/simpleserver.py $port
}

function simple-server-running()
{
    screen -list | grep httpserver | awk '{print $1}'
}