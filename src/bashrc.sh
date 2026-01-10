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

function simple-server-open()
{
    list_output=$(simple-server-list)
    if echo "$list_output" | grep -q "No running servers found."; then
        echo "$list_output"
        return 1
    fi

    if [ -n "$ZSH_VERSION" ]; then
        typeset -a server_lines
    else
        server_lines=()
    fi
    while IFS= read -r line; do
        server_lines+=("$line")
    done < <(printf '%s\n' "$list_output" | tail -n +2 | sed '/^[[:space:]]*$/d')
    if [ "${#server_lines[@]}" -eq 0 ]; then
        echo "No running servers found."
        return 1
    fi

    echo "Select a server to open:"
    index=1
    for line in "${server_lines[@]}"; do
        IFS=$'\t' read -r pid address port started cwd <<< "$line"
        printf "%2d) %s:%s (%s) %s\n" "$index" "$address" "$port" "$started" "$cwd"
        index=$((index + 1))
    done

    printf "Enter selection [1-%s]: " "${#server_lines[@]}"
    if [ -n "$ZSH_VERSION" ]; then
        read -r selection
    else
        read -r selection
    fi
    if ! [[ "$selection" =~ ^[0-9]+$ ]] || [ "$selection" -lt 1 ] || [ "$selection" -gt "${#server_lines[@]}" ]; then
        echo "Invalid selection."
        return 1
    fi

    IFS=$'\t' read -r pid address port started cwd <<< "${server_lines[$((selection - 1))]}"
    if [ "$address" = "0.0.0.0" ]; then
        address="localhost"
    fi
    open-url "http://${address}:${port}/"
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
