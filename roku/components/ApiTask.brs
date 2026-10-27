sub init()
    m.top.functionName = "serve"
end sub

sub serve()
    port = CreateObject("roMessagePort")
    m.top.observeField("request", port)
    while true
        msg = wait(0, port)
        if type(msg) = "roSGNodeEvent"
            req = msg.getData()
            if req <> invalid and req.url <> invalid then send(req)
        end if
    end while
end sub

sub send(req as object)
    xfer = CreateObject("roUrlTransfer")
    port = CreateObject("roMessagePort")
    xfer.SetMessagePort(port)
    xfer.SetUrl(req.url)

    timeout = 25000
    if req.timeout <> invalid then timeout = req.timeout

    code = -1
    body = ""
    if xfer.AsyncGetToString()
        event = wait(timeout, port)
        if type(event) = "roUrlEvent"
            code = event.GetResponseCode()
            body = event.GetString()
        else
            xfer.AsyncCancel()
        end if
    end if

    m.top.response = { id: req.id, tag: req.tag, code: code, body: body }
end sub
