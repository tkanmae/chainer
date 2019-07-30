import glob
import itertools
import os
import random
import shutil
import tempfile
import time
import unittest

import mock
import pytest

from chainer import testing
from chainer import training
from chainer.training import extensions
from chainer.training.extensions._snapshot import _find_snapshot_files
from chainer.training.extensions._snapshot import _find_latest_snapshot
from chainer.training.extensions._snapshot import _find_stale_snapshots


class TestSnapshot(unittest.TestCase):

    def test_call(self):
        t = mock.MagicMock()
        c = mock.MagicMock(side_effect=[True, False])
        w = mock.MagicMock()
        snapshot = extensions.snapshot(target=t, condition=c, writer=w)
        trainer = mock.MagicMock()
        snapshot(trainer)
        snapshot(trainer)

        assert c.call_count == 2
        assert w.call_count == 1

    def test_savefun_and_writer_exclusive(self):
        # savefun and writer arguments cannot be specified together.
        def savefun(*args, **kwargs):
            assert False
        writer = extensions.snapshot_writers.SimpleWriter()
        with pytest.raises(TypeError):
            extensions.snapshot(savefun=savefun, writer=writer)

        trainer = mock.MagicMock()
        with pytest.raises(TypeError):
            extensions.snapshot_object(trainer, savefun=savefun, writer=writer)


class TestSnapshotSaveFile(unittest.TestCase):

    def setUp(self):
        self.trainer = testing.get_trainer_with_mock_updater()
        self.trainer.out = '.'
        self.trainer._done = True

    def tearDown(self):
        if os.path.exists('myfile.dat'):
            os.remove('myfile.dat')

    def test_save_file(self):
        w = extensions.snapshot_writers.SimpleWriter()
        snapshot = extensions.snapshot_object(self.trainer, 'myfile.dat',
                                              writer=w)
        snapshot(self.trainer)

        self.assertTrue(os.path.exists('myfile.dat'))

    def test_clean_up_tempdir(self):
        snapshot = extensions.snapshot_object(self.trainer, 'myfile.dat')
        snapshot(self.trainer)

        left_tmps = [fn for fn in os.listdir('.')
                     if fn.startswith('tmpmyfile.dat')]
        self.assertEqual(len(left_tmps), 0)


class TestSnapshotOnError(unittest.TestCase):

    def setUp(self):
        self.trainer = testing.get_trainer_with_mock_updater()
        self.trainer.out = '.'
        self.filename = 'myfile-deadbeef.dat'

    def tearDown(self):
        if os.path.exists(self.filename):
            os.remove(self.filename)

    def test_on_error(self):

        class TheOnlyError(Exception):
            pass

        @training.make_extension(trigger=(1, 'iteration'), priority=100)
        def exception_raiser(trainer):
            raise TheOnlyError()
        self.trainer.extend(exception_raiser)

        snapshot = extensions.snapshot_object(self.trainer, self.filename,
                                              snapshot_on_error=True)
        self.trainer.extend(snapshot)

        self.assertFalse(os.path.exists(self.filename))

        with self.assertRaises(TheOnlyError):
            self.trainer.run()

        self.assertTrue(os.path.exists(self.filename))


@testing.parameterize(*testing.product({'fmt':
                                        ['snapshot_iter_{}',
                                         'snapshot_iter_{}.npz',
                                         '{}_snapshot_man_suffix.npz']}))
class TestFindSnapshot(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.path)

    def test_find_snapshot_files(self):
        files = (self.fmt.format(i) for i in range(1, 100))
        noise = ('dummy-foobar-iter{}'.format(i) for i in range(10, 304))
        noise2 = ('tmpsnapshot_iter_{}'.format(i) for i in range(10, 304))

        for file in itertools.chain(noise, files, noise2):
            file = os.path.join(self.path, file)
            open(file, 'w').close()

        snapshot_files = _find_snapshot_files(self.fmt, self.path)

        answer = [self.fmt.format(i) for i in range(1, 100)]
        assert len(snapshot_files) == 99
        timestamps, snapshot_files = zip(*snapshot_files)
        answer.sort()
        snapshot_files = sorted(list(snapshot_files))
        for lhs, rhs in zip(answer, snapshot_files):
            assert lhs == rhs

    def test_find_latest_snapshot(self):
        files = [self.fmt.format(i) for i in range(1, 100)]

        for file in files[:-1]:
            file = os.path.join(self.path, file)
            open(file, 'w').close()
            time.sleep(2*10e-3)
        file = os.path.join(self.path, files[-1])
        open(file, 'w').close()

        assert self.fmt.format(99) == _find_latest_snapshot(self.fmt,
                                                            self.path)


@testing.parameterize(*testing.product({'fmt':
                                        ['snapshot_iter_{}_{}',
                                         'snapshot_iter_{}_{}.npz',
                                         '{}_snapshot_man_{}-suffix.npz',
                                         'snapshot_iter_{}.{}']}))
class TestFindSnapshot2(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mkdtemp()
        self.files = (self.fmt.format(i*10, j*10) for i, j
                      in itertools.product(range(0, 10), range(0, 10)))

    def tearDown(self):
        shutil.rmtree(self.path)

    def test_find_snapshot_files(self):
        noise = ('tmpsnapshot_iter_{}.{}'.format(i, j)
                 for i, j in zip(range(10, 304), range(10, 200)))

        for file in itertools.chain(noise, self.files):
            file = os.path.join(self.path, file)
            open(file, 'w').close()

        snapshot_files = _find_snapshot_files(self.fmt, self.path)

        answer = [self.fmt.format(i*10, j*10)
                  for i, j in itertools.product(range(0, 10), range(0, 10))]

        timestamps, snapshot_files = zip(*snapshot_files)
        answer.sort()
        snapshot_files = sorted(list(snapshot_files))
        for lhs, rhs in zip(answer, snapshot_files):
            assert lhs == rhs


@testing.parameterize(*testing.product({'length_retain':
                                        [(100, 30), (10, 30), (1, 1000),
                                         (1000, 1), (1, 1), (1, 3), (2, 3)]}))
class TestFindStaleSnapshot(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.path)

    def test_find_stale_snapshot(self):
        length, retain = self.length_retain
        fmt = 'snapshot_iter_{}'
        files = random.sample([fmt.format(i) for i in range(0, length)],
                              length)

        for file in files[:-1]:
            file = os.path.join(self.path, file)
            open(file, 'w').close()
            time.sleep(10e-3)
        file = os.path.join(self.path, files[-1])
        open(file, 'w').close()

        stale = list(_find_stale_snapshots(fmt, self.path, retain))
        assert max(length-retain, 0) == len(list(stale))
        stales = [fmt.format(i) for i in range(0, max(length-retain, 0))]
        for lhs, rhs in zip(stales, stale):
            lhs == rhs


class TestRemoveStaleSnapshots(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.path)

    def test_remove_stale_snapshots(self):
        fmt = 'snapshot_iter_{.updater.iteration}'
        retain = 3
        snapshot = extensions.snapshot(filename=fmt, num_retain=retain,
                                       autoload=False)

        trainer = testing.get_trainer_with_mock_updater()
        trainer.out = self.path
        trainer.extend(snapshot, trigger=(1, 'iteration'))
        trainer.run()
        assert 10 == trainer.updater.iteration
        assert trainer._done

        pattern = os.path.join(trainer.out, "snapshot_iter_*")
        found = [path for path in glob.glob(pattern)]
        assert retain == len(found)
        found.sort()

        for lhs, rhs in zip(['snapshot_iter_{}'.format(i)
                             for i in range(8, 10)], found):
            lhs == rhs

        trainer2 = testing.get_trainer_with_mock_updater()
        trainer2.out = self.path
        assert not trainer2._done
        snapshot2 = extensions.snapshot(filename=fmt, autoload=True)
        # Just making sure no error occurs
        snapshot2.initialize(trainer2)


testing.run_module(__name__, __file__)
