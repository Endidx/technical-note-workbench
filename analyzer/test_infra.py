import hashlib
import io
import unittest
from unittest.mock import Mock

from . import infra


class ArchiveTests(unittest.TestCase):
    def test_utf8_content_address_does_not_depend_on_filename(self):
        store = Mock()
        text = "# 笔记\r\n修改默认值。"
        key = infra.archive(store, text)
        self.assertEqual(key, hashlib.sha256(text.encode()).hexdigest())
        bucket, name, stream, size = store.put_object.call_args.args
        self.assertEqual((bucket, name, size, stream.read()), (infra.BUCKET, key, len(text.encode()), text.encode()))

    def test_restore_rejects_corrupt_content_and_closes_connection(self):
        store = Mock()
        stream = Mock(wraps=io.BytesIO(b'bad'))
        stream.release_conn = Mock()
        store.get_object.return_value = stream
        with self.assertRaises(OSError):
            infra.restore(store, "0" * 64)
        stream.close.assert_called_once()
        stream.release_conn.assert_called_once()
