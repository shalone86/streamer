sub init()
    m.img = m.top.findNode("img")
    m.big = m.top.findNode("big")
    m.name = m.top.findNode("name")
    m.badge = m.top.findNode("badge")
    m.badgeText = m.top.findNode("badgeText")
end sub

sub show()
    item = m.top.itemContent
    if item = invalid then return
    if item.action = "title"
        m.img.uri = item.HDPosterUrl
        m.big.text = ""
        name = item.title
        if item.year <> invalid and item.year <> "" then name = name + " (" + item.year + ")"
        m.name.text = name
        look = serviceLook(item.service)
        m.badge.color = look.color
        m.badgeText.text = look.name
        m.badge.visible = true
    else
        m.img.uri = ""
        m.big.text = item.title
        m.name.text = ""
        m.badge.visible = false
    end if
end sub

function serviceLook(service as string) as object
    looks = {
        netflix: { name: "Netflix", color: "0xE50914FF" },
        peacock: { name: "Peacock", color: "0x000000E0" },
        tubi: { name: "Tubi", color: "0x7408FFFF" },
        sling: { name: "Sling", color: "0x0072CEFF" },
    }
    look = looks[service]
    if look = invalid then look = { name: service, color: "0x333333FF" }
    return look
end function
