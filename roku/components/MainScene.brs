' What's on (genre rows and search), and the stream from the server with the remote's buttons sent back to it.

sub init()
    m.rows = m.top.findNode("rows")
    m.menu = m.top.findNode("menu")
    m.status = m.top.findNode("status")
    m.video = m.top.findNode("video")
    m.keys = m.top.findNode("keys")
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

    m.menuItems = [
        { title: "Search", action: "search" },
        { title: "Netflix", service: "netflix", action: "service" },
        { title: "Peacock", service: "peacock", action: "service" },
        { title: "Tubi", service: "tubi", action: "service" },
        { title: "Sling", service: "sling", action: "service" },
        { title: "Continue where I left off", service: "", action: "service" },
        { title: "Help", action: "help" },
        { title: "Server address...", action: "server" },
    ]
    m.home = makeRows([])
    m.rows.content = m.home
    m.showingResults = false
    m.rows.observeField("rowItemSelected", "onTileSelected")
    m.retryTimer = CreateObject("roSGNode", "Timer")
    m.retryTimer.duration = 20
    m.retryTimer.observeField("fire", "loadCatalog")

    m.video.observeField("state", "onVideoState")
    m.repeatTimer.observeField("fire", "onRepeat")
    m.badgeTimer.observeField("fire", "hideBadge")

    m.watching = false
    m.starting = false
    m.mode = "keys"
    m.backTimer = CreateObject("roTimespan")
    m.heldKey = ""
    m.repeatCount = 0

    m.rows.setFocus(true)
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
            loadCatalog()
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
    else if r.tag = "catalog"
        onCatalog(r)
    else if r.tag = "search"
        onSearch(r)
    else if r.tag = "button" and r.code = 200
        data = ParseJson(r.body)
        if data <> invalid and data.badge <> invalid and data.badge <> "" then showBadge(data.badge)
    else if r.tag = "button" and r.code <> 404
        showBadge("Server not responding")
    end if
end sub

function errorText(r as object) as string
    if r.code < 0 then return ": no answer from the server."
    data = ParseJson(r.body)
    if data <> invalid and data.error <> invalid then return ": " + data.error
    return " (error " + r.code.ToStr() + ")."
end function

' ------------------------------------------------------------ rows

' The menu row, then one row per genre: [{title, items: [{title, year, img, service, url}]}]
function makeRows(genres as object) as object
    root = CreateObject("roSGNode", "ContentNode")
    menu = root.createChild("ContentNode")
    menu.title = "Menu"
    for each item in m.menuItems
        tile = menu.createChild("ContentNode")
        tile.title = item.title
        fields = { action: item.action, service: "", url: "", year: "" }
        if item.service <> invalid then fields.service = item.service
        tile.addFields(fields)
    end for
    for each genre in genres
        row = root.createChild("ContentNode")
        row.title = genre.title
        for each t in genre.items
            tile = row.createChild("ContentNode")
            tile.title = t.title
            tile.HDPosterUrl = t.img
            year = ""
            if t.year <> invalid then year = t.year.ToStr()
            tile.addFields({ action: "title", service: t.service, url: t.url, year: year })
        end for
    end for
    return root
end function

sub loadCatalog()
    callServer("/api/catalog", "catalog")
end sub

sub onCatalog(r as object)
    data = invalid
    if r.code = 200 then data = ParseJson(r.body)
    if data = invalid
        m.status.text = "Couldn't get the list of titles" + errorText(r)
        return
    end if
    if data.rows.Count() = 0
        m.status.text = "Getting the list of titles for the first time (a minute or two)..."
        m.retryTimer.control = "start"
        return
    end if
    m.home = makeRows(data.rows)
    if not m.showingResults then m.rows.content = m.home
end sub

sub onTileSelected()
    if m.watching then return
    at = m.rows.rowItemSelected
    tile = m.rows.content.getChild(at[0]).getChild(at[1])
    if tile.action = "title"
        startWatching("/api/open?play=1&url=" + urlEncode(tile.url))
    else if tile.action = "service"
        if tile.service = ""
            startWatching("")
        else
            startWatching("/api/open?service=" + tile.service)
        end if
    else if tile.action = "search"
        askSearch()
    else if tile.action = "help"
        showHelp()
    else if tile.action = "server"
        askServer()
    end if
end sub

function urlEncode(text as string) as string
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    bytes = CreateObject("roByteArray")
    bytes.FromAsciiString(text) ' the string's UTF-8 bytes
    hex = bytes.ToHexString() ' two upper-case hex digits per byte
    out = ""
    for i = 0 to bytes.Count() - 1
        c = Chr(bytes[i])
        if bytes[i] < 128 and Instr(1, safe, c) > 0
            out = out + c
        else
            out = out + "%" + Mid(hex, i * 2 + 1, 2)
        end if
    end for
    return out
end function

' ------------------------------------------------------------ search

sub askSearch()
    dialog = CreateObject("roSGNode", "StandardKeyboardDialog")
    dialog.title = "Search"
    dialog.message = ["A movie or show on Netflix, Peacock, Tubi or Sling"]
    dialog.buttons = ["Search", "Cancel"]
    dialog.observeField("buttonSelected", "onSearchDialog")
    m.top.dialog = dialog
end sub

sub onSearchDialog()
    dialog = m.top.dialog
    query = dialog.text.Trim()
    if dialog.buttonSelected = 0 and query <> ""
        m.query = query
        m.status.text = "Searching for " + query + "..."
        callServer("/api/search?q=" + urlEncode(query), "search")
    end if
    dialog.close = true
    m.rows.setFocus(true)
end sub

sub onSearch(r as object)
    data = invalid
    if r.code = 200 then data = ParseJson(r.body)
    if data = invalid
        m.status.text = "Search didn't work" + errorText(r)
        return
    end if
    if data.items.Count() = 0
        m.status.text = "Nothing found for " + m.query
        return
    end if
    m.rows.content = makeRows([{ title: "Results for " + Chr(34) + m.query + Chr(34), items: data.items }])
    m.rows.jumpToRowItem = [1, 0]
    m.showingResults = true
    m.status.text = "Back: all titles"
end sub

sub showHome()
    m.showingResults = false
    m.rows.content = m.home
    m.rows.jumpToRowItem = [0, 0]
    m.status.text = "Connected to " + m.server
end sub

sub showHelp()
    dialog = CreateObject("roSGNode", "StandardMessageDialog")
    dialog.title = "While watching"
    dialog.message = [
        "Arrows, OK: move and select on the page",
        "Play: pause / play",
        "Rewind / Fast-fwd: back / ahead 10 seconds",
        "Replay: full screen (f)",
        "* : switch to a mouse pointer and back",
        "Back: previous page. Hold Back: return here",
    ]
    dialog.buttons = ["OK"]
    dialog.observeField("buttonSelected", "closeDialog")
    m.top.dialog = dialog
end sub

sub closeDialog()
    m.top.dialog.close = true
    m.rows.setFocus(true)
end sub

' ------------------------------------------------------------ watching

' openPath: "/api/open?..." to load something first, or "" to keep what's on screen.
sub startWatching(openPath as string)
    if m.starting then return
    m.starting = true
    m.status.text = "Starting..."
    if openPath = ""
        callServer("/api/stream/start", "start")
    else
        callServer(openPath, "open")
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
    m.rows.setFocus(true)
end sub

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
    ' Focusing the Scene leaves the hidden list focused (it would eat the arrows and OK).
    m.keys.setFocus(true)
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
    m.rows.setFocus(true)
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
    if not m.watching
        ' Back from search results goes back to all titles; otherwise it leaves the channel.
        if key = "back" and press and m.showingResults
            showHome()
            return true
        end if
        return false
    end if

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
