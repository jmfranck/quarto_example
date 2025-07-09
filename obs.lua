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
          local prefix_parts = {}
          if when then table.insert(prefix_parts, when) end
          if author then table.insert(prefix_parts, author) end
          local prefix = nil
          if #prefix_parts > 0 then
            local txt = table.concat(prefix_parts, ' ') .. ':'
            prefix = pandoc.Span(
              { pandoc.Str(txt) },
              pandoc.Attr('', {}, { style = 'font-size:85%; color:green;' })
            )
          end
          local body = pandoc.Span(
            pandoc.List(inner),
            pandoc.Attr('', {}, { style = 'color:blue;' })
          )
          if prefix then
            table.insert(out, prefix)
            table.insert(out, pandoc.Space())
          end
          table.insert(out, body)
          i = j + 1
          goto continue
        end
      elseif el.text == '<obs>' then
        -- simple <obs> with no attributes
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
          local body = pandoc.Span(
            pandoc.List(inner),
            pandoc.Attr('', {}, { style = 'color:blue;' })
          )
          table.insert(out, body)
          i = j + 1
          goto continue
        end
      end
    end
    table.insert(out, el)
    i = i + 1
    ::continue::
  end
  return out
end

-- Convert <err>...</err> blocks spanning multiple paragraphs into a styled Div
function Blocks(blocks)
  local out = pandoc.List{}
  local i = 1
  while i <= #blocks do
    local blk = blocks[i]
    local handled = false
    if blk.t == 'Para' then
      local inlines = blk.content
      for pos, inline in ipairs(inlines) do
        if inline.t == 'RawInline' and inline.format == 'html' and inline.text == '<err>' then
          local inner = pandoc.List{}
          local closing_in_para = false
          local rest = pandoc.List{}
          local j = pos + 1
          while j <= #inlines do
            local cur = inlines[j]
            if cur.t == 'RawInline' and cur.format == 'html' and cur.text == '</err>' then
              closing_in_para = true
              break
            else
              rest:insert(cur)
            end
            j = j + 1
          end
          if #rest > 0 then
            inner:insert(pandoc.Para(rest))
          end
          if not closing_in_para then
            i = i + 1
            while i <= #blocks do
              local cur = blocks[i]
              local closing_found = false
              if cur.t == 'Para' then
                for cpos, cin in ipairs(cur.content) do
                  if cin.t == 'RawInline' and cin.format == 'html' and cin.text == '</err>' then
                    if cpos > 1 then
                      local before = pandoc.List{}
                      for k = 1, cpos - 1 do
                        before:insert(cur.content[k])
                      end
                      if #before > 0 then
                        inner:insert(pandoc.Para(before))
                      end
                    end
                    closing_found = true
                    break
                  end
                end
              end
              if closing_found then
                break
              else
                inner:insert(cur)
              end
              i = i + 1
            end
          end
          local header = pandoc.Para({
            pandoc.Span({pandoc.Str('DEBUG:')}, pandoc.Attr('', {}, {style = 'color:grey;'}))
          })
          local body = pandoc.Div(inner, pandoc.Attr('', {}, {style = 'margin:10px; border:0px;'}))
          local div = pandoc.Div({header, body}, pandoc.Attr('', {}, {style = 'margin:0px; border:1px solid grey; padding:0px;'}))
          out:insert(div)
          handled = true
          break
        end
      end
    end
    if not handled then
      out:insert(blk)
    end
    i = i + 1
  end
  return out
end

