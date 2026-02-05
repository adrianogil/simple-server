# @tool simple-http-server
alias simple-server-py='python3 $SIMPLE_SERVER_DIR/simpleserver.py'
alias sv='simple-server'
alias svl='simple-server-list'
alias svo='simple-server-open'
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

    if [ -n "$1" ] && [ -d "$1" ]; then
        target_path=$(cd "$1" && pwd)
    else
        target_path=$PWD
    fi

    existing_port=$(simple-server-find-existing "$target_path")
    if [ -n "$existing_port" ]; then
        echo "A server is already running for $target_path on port $existing_port."
        read -r -p "Start another server? [y/N] " reply
        case "$reply" in
            [yY][eE][sS]|[yY])
                ;;
            *)
                open-url "http://localhost:${existing_port}/"
                return 0
                ;;
        esac
    fi

    local_path=$(echo ${target_path#"$HOME"} | tr "/" "_")

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

function simple-server-open()
{
    if ! command -v fzf >/dev/null 2>&1; then
        echo "fzf is required to select a server."
        return 1
    fi

    selection=$(python3 $SIMPLE_SERVER_DIR/simpleserver.py list --porcelain | fzf --prompt="Select server: ")
    if [ -z "$selection" ]; then
        return 1
    fi

    IFS=$'\t' read -r port cwd <<< "$selection"
    if [ -z "$port" ]; then
        echo "No running servers found."
        return 1
    fi
    open-url "http://localhost:${port}/"
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

    existing_port=$(simple-server-find-existing "$PWD")
    if [ -n "$existing_port" ]; then
        echo "A server is already running for $PWD on port $existing_port."
        read -r -p "Start another server? [y/N] " reply
        case "$reply" in
            [yY][eE][sS]|[yY])
                ;;
            *)
                open-url "http://localhost:${existing_port}/${target_html}"
                return 0
                ;;
        esac
    fi

    port=$(rnd-port)
    simple-server $port
    echo "Serve HTML file on port "$port
    open-url http://localhost:$port/$target_html
}

function simple-server-find-existing()
{
    target_path=$1
    if [ -z "$target_path" ]; then
        return 1
    fi

    python3 $SIMPLE_SERVER_DIR/simpleserver.py list --porcelain 2>/dev/null | \
        while IFS=$'\t' read -r port cwd; do
            if [ "$cwd" = "$target_path" ]; then
                echo "$port"
                break
            fi
        done
}
