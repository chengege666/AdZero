# OpenClash depends on ruby-yaml, not ruby-json. Psych.to_json can still emit
# YAML-only escapes (\U, \e, \L...) and folded lines. Emit strict JSON from the
# safely loaded primitive tree instead; never repair escapes in serialized text.
require 'yaml'

def adzero_json(value, depth = 0)
  raise ArgumentError, 'YAML nesting limit' if depth > 100
  case value
  when Hash
    '{' + value.map do |key, item|
      raise ArgumentError, 'YAML mapping keys must be strings' unless key.is_a?(String)
      adzero_json(key, depth + 1) + ':' + adzero_json(item, depth + 1)
    end.join(',') + '}'
  when Array
    '[' + value.map { |item| adzero_json(item, depth + 1) }.join(',') + ']'
  when String
    text = value.encode(Encoding::UTF_8)
    raise ArgumentError, 'Invalid YAML encoding' unless text.valid_encoding?
    '"' + text.gsub(/["\\\x00-\x1f]/) { |char| format('\\u%04x', char.ord) } + '"'
  when Integer
    value.to_s
  when Float
    raise ArgumentError, 'Non-finite YAML number' unless value.finite?
    value.to_s
  when TrueClass then 'true'
  when FalseClass then 'false'
  when NilClass then 'null'
  else raise ArgumentError, 'Unsupported YAML value'
  end
end

begin
  data = YAML.safe_load(File.read(ARGV.fetch(0), encoding: 'UTF-8'), aliases: true)
  $stdout.write(adzero_json(data), "\n")
rescue StandardError
  warn 'AdZero: YAML configuration could not be safely converted'
  exit 1
end
