# @tool simple-http-server
alias simple-server-py='python3 $SIMPLE_SERVER_DIR/simpleserver.py'
alias sv='simple-server'
alias svl='simple-server-list'
# Improved HTTP Server with upload and directory download
# Based on https://gist.github.com/UniIsland/3346170#file-simplehttpserverwithupload-py
# Based on https://stackoverflow.com/questions/2573670/download-whole-directories-in-python-simplehttpserver
# Simple HTTP Server
function simple-server()
{
    if [ -n "$1" ] && [[ "$1" != -* ]]
    then
        port=$1
        shift
    else
        port=8080
    fi

    local_path=$(echo ${PWD#"$HOME"} | tr "/" "_")

    echo "Lets run simple-server in port "$port" and in the path "$PWD
    screen -S simpleserver-$port-$local_path -dm python3 $SIMPLE_SERVER_DIR/simpleserver.py $port "$@"
}

function simple-server-rnd()
{
    port=$(rnd-port)
    screen -S simpleserver-$port-$PWD -dm python3 $SIMPLE_SERVER_DIR/simpleserver.py $port
}

function simple-server-running()
{
    screen -list | grep httpserver | awk '{print $1}'
}

function simple-server-list()
{
    python3 $SIMPLE_SERVER_DIR/simpleserver.py list
}

function simple-upload()
{
    upload_target=$1
    server_address=$2

    python3 $SIMPLE_SERVER_DIR/sendfile.py ${upload_target} ${server_address}
}

function simple-html-serve()
{
    target_html=$1
    port=$(rnd-port)
    simple-server $port
    echo "Serve HTML file on port "$port
    open-url http://localhost:$port/$target_html
}
