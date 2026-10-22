"""Strict JSON interoperability with the ruby-yaml shipped by OpenClash."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

READER=Path(__file__).resolve().parents[1]/'luci-app-adzero/root/usr/libexec/adzero/yaml-json.rb'


@unittest.skipUnless(shutil.which('ruby'),'real Ruby required')
class YAMLReaderTest(unittest.TestCase):
    def convert(self,raw,success=True):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.yaml';path.write_text(raw,encoding='utf-8')
            result=subprocess.run(['ruby',str(READER),str(path)],text=True,capture_output=True,timeout=5)
        self.assertEqual(result.returncode==0,success,result.stderr)
        if success:return json.loads(result.stdout)
        self.assertEqual(result.stdout,'')
        self.assertNotIn('PRIVATE',result.stderr)

    def test_json_primitives_and_unicode_mapping_keys_round_trip(self):
        value={'🚀 节点 🇭🇰':[True,False,None,42,-17,1.25,1.5e40,{'中文':'literal \\U0001F680 \\x1b \\u001b "'}]}
        self.assertEqual(self.convert(json.dumps(value,ensure_ascii=False)),value)

    def test_all_ascii_control_characters_are_valid_json_escapes(self):
        value={'controls':''.join(chr(i) for i in range(32))}
        self.assertEqual(self.convert(json.dumps(value)),value)

    def test_yaml_specific_escapes_are_decoded_before_json_encoding(self):
        raw='value: "\\a\\v\\e\\N\\_\\L\\P\\U0001F680"\n'
        self.assertEqual(self.convert(raw),{'value':'\x07\x0b\x1b\u0085\u00a0\u2028\u2029🚀'})

    def test_anchors_preserve_values(self):
        self.assertEqual(self.convert('a: &data ["🚀", true, null]\nb: *data\n'),{'a':['🚀',True,None],'b':['🚀',True,None]})

    def test_cyclic_aliases_fail_with_bounded_nesting(self):
        self.convert('value: &cycle [*cycle]\n',success=False)

    def test_nonfinite_numbers_are_rejected(self):
        for token in ('.inf','-.inf','.nan'):
            with self.subTest(token=token):self.convert('PRIVATE: '+token+'\n',success=False)

    def test_object_tags_cannot_instantiate_ruby_objects(self):
        self.convert('PRIVATE: !ruby/object:Object {}\n',success=False)

    def test_non_string_mapping_keys_are_rejected(self):
        self.convert('42: PRIVATE\n',success=False)
