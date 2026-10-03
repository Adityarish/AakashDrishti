using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace AakashDrishti.Viewer.Loading
{
    /// <summary>
    /// Minimal JSON reader. JsonUtility cannot read nested arrays such as
    /// "footprint": [[x,z],...], and Newtonsoft needs IL2CPP stripping care, so we parse to
    /// Dictionary&lt;string,object&gt; / List&lt;object&gt; / string / double / bool / null.
    /// </summary>
    public static class MiniJson
    {
        public static object Parse(string json)
        {
            if (string.IsNullOrEmpty(json)) throw new FormatException("empty JSON document");
            var p = new Parser(json);
            object v = p.ParseValue();
            p.SkipWhitespace();
            if (!p.AtEnd) throw new FormatException($"unexpected trailing characters at position {p.Position}");
            return v;
        }

        sealed class Parser
        {
            readonly string s;
            int i;

            public Parser(string text)
            {
                s = text;
                // Skip UTF-8 BOM if the server sent one.
                if (s.Length > 0 && s[0] == '﻿') i = 1;
            }

            public int Position => i;
            public bool AtEnd => i >= s.Length;

            public void SkipWhitespace()
            {
                while (i < s.Length && char.IsWhiteSpace(s[i])) i++;
            }

            public object ParseValue()
            {
                SkipWhitespace();
                if (AtEnd) throw new FormatException("unexpected end of JSON");
                char c = s[i];
                switch (c)
                {
                    case '{': return ParseObject();
                    case '[': return ParseArray();
                    case '"': return ParseString();
                    case 't': Expect("true"); return true;
                    case 'f': Expect("false"); return false;
                    case 'n': Expect("null"); return null;
                    default: return ParseNumber();
                }
            }

            void Expect(string word)
            {
                if (string.CompareOrdinal(s, i, word, 0, word.Length) != 0)
                    throw new FormatException($"unexpected token at position {i}");
                i += word.Length;
            }

            Dictionary<string, object> ParseObject()
            {
                var d = new Dictionary<string, object>();
                i++; // {
                SkipWhitespace();
                if (i < s.Length && s[i] == '}') { i++; return d; }
                while (true)
                {
                    SkipWhitespace();
                    if (AtEnd || s[i] != '"') throw new FormatException($"expected property name at position {i}");
                    string key = ParseString();
                    SkipWhitespace();
                    if (AtEnd || s[i] != ':') throw new FormatException($"expected ':' at position {i}");
                    i++;
                    d[key] = ParseValue();
                    SkipWhitespace();
                    if (AtEnd) throw new FormatException("unterminated object");
                    if (s[i] == ',') { i++; continue; }
                    if (s[i] == '}') { i++; return d; }
                    throw new FormatException($"expected ',' or '}}' at position {i}");
                }
            }

            List<object> ParseArray()
            {
                var l = new List<object>();
                i++; // [
                SkipWhitespace();
                if (i < s.Length && s[i] == ']') { i++; return l; }
                while (true)
                {
                    l.Add(ParseValue());
                    SkipWhitespace();
                    if (AtEnd) throw new FormatException("unterminated array");
                    if (s[i] == ',') { i++; continue; }
                    if (s[i] == ']') { i++; return l; }
                    throw new FormatException($"expected ',' or ']' at position {i}");
                }
            }

            string ParseString()
            {
                i++; // opening quote
                var sb = new StringBuilder();
                while (true)
                {
                    if (AtEnd) throw new FormatException("unterminated string");
                    char c = s[i++];
                    if (c == '"') return sb.ToString();
                    if (c != '\\') { sb.Append(c); continue; }
                    if (AtEnd) throw new FormatException("unterminated escape");
                    char e = s[i++];
                    switch (e)
                    {
                        case '"': sb.Append('"'); break;
                        case '\\': sb.Append('\\'); break;
                        case '/': sb.Append('/'); break;
                        case 'b': sb.Append('\b'); break;
                        case 'f': sb.Append('\f'); break;
                        case 'n': sb.Append('\n'); break;
                        case 'r': sb.Append('\r'); break;
                        case 't': sb.Append('\t'); break;
                        case 'u':
                            if (i + 4 > s.Length) throw new FormatException("bad \\u escape");
                            sb.Append((char)int.Parse(s.Substring(i, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture));
                            i += 4;
                            break;
                        default: throw new FormatException($"bad escape '\\{e}' at position {i}");
                    }
                }
            }

            double ParseNumber()
            {
                int start = i;
                while (i < s.Length && "+-0123456789.eE".IndexOf(s[i]) >= 0) i++;
                if (start == i) throw new FormatException($"unexpected character '{s[i]}' at position {i}");
                if (!double.TryParse(s.Substring(start, i - start), NumberStyles.Float, CultureInfo.InvariantCulture, out double d))
                    throw new FormatException($"bad number at position {start}");
                return d;
            }
        }
    }
}
