-- obs.lua

-- Process custom <obs> tags. These appear in the input as RawInline elements
-- for the opening and closing tags. The content between them should continue to
-- be parsed as normal markdown. This filter converts:
--   <obs author="NAME" date="DATE">content</obs>
-- into a span containing the author/date (smaller and green) followed by the
-- content colored blue.

local function parse_attrs(attr)
  local author = attr:match('author="([^"]+)"')
  local when = attr:match('time="([^"]+)"') or attr:match('date="([^"]+)"')
  return author, when
end

function Inlines(inls)
  local out = {}
  local i = 1
  while i <= #inls do
    local el = inls[i]
    if el.t == 'RawInline' and el.format == 'html' then
      local attr = el.text:match('^<obs%s+([^>]+)>$')
      if attr then
        -- gather inner content up to the closing tag
        local inner = {}
        local j = i + 1
        while j <= #inls do
          local cur = inls[j]
          if cur.t == 'RawInline' and cur.format == 'html' and cur.text:match('^</obs>$') then
            break
          else
            table.insert(inner, cur)
          end
          j = j + 1
        end
        if j <= #inls then
          local author, when = parse_attrs(attr)
          if author and when then
            local prefix = pandoc.Span(
              { pandoc.Str(when .. ' ' .. author .. ':') },
              pandoc.Attr('', {}, { style = 'font-size:85%; color:green;' })
            )
            local body = pandoc.Span(
              pandoc.List(inner),
              pandoc.Attr('', {}, { style = 'color:blue;' })
            )
            table.insert(out, prefix)
            table.insert(out, pandoc.Space())
            table.insert(out, body)
            i = j + 1
            goto continue
          end
        end
      end
    end
    table.insert(out, el)
    i = i + 1
    ::continue::
  end
  return out
end

-- Convert <err>...</err> segments within a paragraph into a styled Div
function Para(para)
  local out_blocks = pandoc.List{}
  local buf = pandoc.List{}
  local i = 1
  local inlines = para.content
  while i <= #inlines do
    local el = inlines[i]
    if el.t == 'RawInline' and el.format == 'html' and el.text == '<err>' then
      if #buf > 0 then
        out_blocks:insert(pandoc.Para(buf))
        buf = pandoc.List{}
      end
      local inner = pandoc.List{}
      i = i + 1
      while i <= #inlines do
        local cur = inlines[i]
        if cur.t == 'RawInline' and cur.format == 'html' and cur.text == '</err>' then
          break
        else
          inner:insert(cur)
        end
        i = i + 1
      end
      local header = pandoc.Para({
        pandoc.Span({pandoc.Str('DEBUG:')}, pandoc.Attr('', {}, {style = 'color:grey;'}))
      })
      local body = pandoc.Para(inner)
      local div = pandoc.Div({header, body}, pandoc.Attr('', {}, {style = 'margin:10px; border:1px solid grey;'}))
      out_blocks:insert(div)
    else
      buf:insert(el)
    end
    i = i + 1
  end
  if #out_blocks == 0 then
    return nil
  else
    if #buf > 0 then
      out_blocks:insert(pandoc.Para(buf))
    end
    return out_blocks
  end
end

