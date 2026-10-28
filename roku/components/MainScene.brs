' The menu, and the stream from the server with the remote's buttons sent back to it.

sub init()
    m.list = m.top.findNode("list")
    m.menu = m.top.findNode("menu")
    m.status = m.top.findNode("status")
    m.video = m.top.findNode("video")
    m.badge = m.top.findNode("badge")
    m.badgeText = m.top.findNode("badgeText")
    m.repeatTimer = m.top.findNode("repeatTimer")
    m.badgeTimer = m.top.findNode("badgeTimer")

    m.api = CreateObject("roSGNode", "ApiTask")
    m.api.observeField("response", "onResponse")
    m.api.control = "RUN"
    m.reqId = 0

    m.registry = CreateObject("roRegistrySection", "streamer")
    m.server = m.registry.Read("server")
    if m.server = "" then m.server = DefaultServerUrl()

    m.items = [
        { title: "Netflix", service: "netflix", action: "watch" },
        { title: "Peacock", service: "peacock", action: "watch" },
        { title: "Tubi", service: "tubi", action: "watch" },
        { title: "Sling", service: "sling", action: "watch" },
        { title: "Continue where I left off", service: "", action: "watch" },
        { title: "Server address...", service: "", action: "server" },
    ]
    content = CreateObject("roSGNode", "ContentNode")
    for each item in m.items
        content.createChild("ContentNode").title = item.title
    end for
    m.list.content = content
    m.list.observeField("itemSelected", "onItemSelected")

    m.video.observeField("state", "onVideoState")
    m.repeatTimer.observeField("fire", "onRepeat")
    m.badgeTimer.observeField("fire", "hideBadge")

    m.watching = false
    m.starting = false
    m.mode = "keys"
    m.backTimer = CreateObject("roTimespan")
    m.heldKey = ""
    m.repeatCount = 0

    m.list.setFocus(true)
    checkServer()
end sub

' ------------------------------------------------------------ server calls

sub callServer(path as string, tag as string)
    m.reqId = m.reqId + 1
    m.api.request = { id: m.reqId, url: m.server + path, tag: tag }
end sub

sub checkServer()
    if m.server = "" or m.server.Instr("__SERVER_URL__") >= 0
        m.status.text = "Set the server address (last item in the list)."
        return
    end if
    m.status.text = "Connecting to " + m.server + "..."
    callServer("/api/status", "status")
end sub

sub onResponse()
    r = m.api.response
    ok = r.code = 200
    if r.tag = "status"
        if ok
            m.status.text = "Connected to " + m.server
        else
            m.status.text = "Can't reach " + m.server + ". Is the server running? Check the address (last item)."
        end if
    else if r.tag = "open"
        if ok
            callServer("/api/stream/start", "start")
        else
            failStart("Couldn't open that in the browser" + errorText(r))
        end if
    else if r.tag = "start"
        if ok
            playStream()
        else
            failStart("The stream didn't start" + errorText(r))
        end if
    else if r.tag = "button" and r.code <> 200 and r.code <> 404
        showBadge("Server not responding")
    end if
end sub

function errorText(r as object) as string
    if r.code < 0 then return ": no answer from the server."
    data = ParseJson(r.body)
    if data <> invalid and data.error <> invalid then return ": " + data.error
    return " (error " + r.code.ToStr() + ")."
end function

' ------------------------------------------------------------ menu

sub onItemSelected()
    item = m.items[m.list.itemSelected]
    if item.action = "server"
        askServer()
    else
        startWatching(item.service)
    end if
end sub

sub startWatching(service as string)
    if m.starting then return
    m.starting = true
    m.status.text = "Starting..."
    if service = ""
        callServer("/api/stream/start", "start")
    else
        callServer("/api/open?service=" + service, "open")
    end if
end sub

sub failStart(message as string)
    m.starting = false
    m.status.text = message
end sub

sub askServer()
    dialog = CreateObject("roSGNode", "StandardKeyboardDialog")
    dialog.title = "Server address"
    dialog.message = ["Like http://192.168.1.10:8080"]
    dialog.text = m.server
    if m.server.Instr("__SERVER_URL__") >= 0 then dialog.text = "http://"
    dialog.buttons = ["Save", "Cancel"]
    dialog.observeField("buttonSelected", "onServerDialog")
    m.top.dialog = dialog
end sub

sub onServerDialog()
    dialog = m.top.dialog
    if dialog.buttonSelected = 0
        url = dialog.text.Trim()
        while url.Right(1) = "/"
            url = url.Left(url.Len() - 1)
        end while
        if url.Instr("://") < 0 then url = "http://" + url
        m.server = url
        m.registry.Write("server", url)
        m.registry.Flush()
        checkServer()
    end if
    dialog.close = true
    m.list.setFocus(true)
end sub

' ------------------------------------------------------------ watching

sub playStream()
    m.starting = false
    content = CreateObject("roSGNode", "ContentNode")
    content.url = m.server + "/hls/index.m3u8"
    content.streamFormat = "hls"
    content.live = true
    m.video.content = content
    m.menu.visible = false
    m.video.visible = true
    m.video.control = "play"
    m.watching = true
    m.top.setFocus(true)
    m.mode = "keys"
    showBadge("Hold Back to leave")
end sub

sub stopWatching()
    m.watching = false
    m.repeatTimer.control = "stop"
    m.video.control = "stop"
    m.video.visible = false
    m.menu.visible = true
    m.status.text = "Connected to " + m.server
    m.list.setFocus(true)
    callServer("/api/stream/stop", "stop")
end sub

sub onVideoState()
    if not m.watching then return
    if m.video.state = "error"
        stopWatching()
        m.status.text = "The video stopped: " + m.video.errorMsg
    else if m.video.state = "finished"
        m.video.control = "play"
    end if
end sub

sub sendButton(key as string, repeat as integer)
    callServer("/api/button?b=" + key + "&mode=" + m.mode + "&n=" + repeat.ToStr(), "button")
end sub

function isArrow(key as string) as boolean
    return key = "up" or key = "down" or key = "left" or key = "right"
end function

sub onRepeat()
    m.repeatCount = m.repeatCount + 1
    sendButton(m.heldKey, m.repeatCount)
end sub

sub showBadge(text as string)
    m.badgeText.text = text
    m.badge.visible = true
    m.badgeTimer.control = "stop"
    if not (m.watching and m.mode = "mouse" and text = "Mouse") then m.badgeTimer.control = "start"
end sub

sub hideBadge()
    m.badge.visible = false
end sub

function onKeyEvent(key as string, press as boolean) as boolean
    if not m.watching then return false

    if key = "back"
        ' A short press is the browser's Back; holding it returns to the menu.
        if press
            m.backTimer.Mark()
        else if m.backTimer.TotalMilliseconds() >= 800
            stopWatching()
        else
            sendButton("back", 0)
        end if
        return true
    end if

    if key = "options"
        if press
            if m.mode = "keys"
                m.mode = "mouse"
                showBadge("Mouse")
            else
                m.mode = "keys"
                showBadge("Keyboard")
            end if
        end if
        return true
    end if

    if press
        sendButton(key, 0)
        if m.mode = "mouse" and isArrow(key)
            m.heldKey = key
            m.repeatCount = 0
            m.repeatTimer.control = "start"
        end if
    else if key = m.heldKey
        m.repeatTimer.control = "stop"
        m.heldKey = ""
    end if
    return true
end function
