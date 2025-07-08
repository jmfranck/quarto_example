-- obs.lua
local read_inline = pandoc.read_inline

function RawInline(el)
  if el.format == "html" then
    local t,a,inner = el.text:match(
      '^<obs%s+time="([^"]+)"%s+author="([^"]-)">(.-)</obs>$'
    )
    if t then
      local prefix = pandoc.Span(
        { pandoc.Str(t .. " " .. a .. ":") },
        { attributes = { style = "color:green;" } }
      )
      local inls = read_inline(inner).content
      local body = pandoc.Span(
        inls,
        { attributes = { style = "color:blue;" } }
      )
      return { prefix, pandoc.Space(), body }
    end
  end
  return nil
end
