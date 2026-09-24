import unittest

from benchmarks.benchmark_jev_bounded_paging import (
    EvaluationCase, RuntimeRequest, catalog_pages, run_episode, score_episode,
)
from jev_agent.models import ChoiceResult


class ScriptedChooser:
    def __init__(self, choices):
        self.choices = iter(choices)
        self.calls = []

    def choose(self, *, state, instructions, options):
        self.calls.append((state, options))
        choice = next(self.choices)
        return ChoiceResult(choice, {o.option_id: float(o.option_id == choice) for o in options}, 1, "scripted")


class BoundedPagingTests(unittest.TestCase):
    def setUp(self):
        self.pages = catalog_pages(7)

    def test_full_interface_cap_and_next_windows(self):
        request = RuntimeRequest(self.pages['p11']['tools'][1]['query'])
        chooser = ScriptedChooser(['NEXT', 'NEXT', 'PAGE:p11', 'p11:op1'])
        trace = run_episode(chooser, request, self.pages)
        self.assertEqual(trace['selected_tool'], 'p11:op1')
        self.assertEqual(trace['submitted_choice_peak'], 8)
        self.assertLessEqual(trace['resident_peak'], 2)
        self.assertEqual(len(trace['calls']), 4)

    def test_wrong_page_is_materialized_without_gold_filter(self):
        request = RuntimeRequest(self.pages['p11']['tools'][0]['query'])
        chooser = ScriptedChooser(['PAGE:p00', 'PAGE', 'NEXT', 'NEXT', 'PAGE:p11', 'p11:op0'])
        trace = run_episode(chooser, request, self.pages)
        loaded = [e['page'] for e in trace['events'] if e['event'] == 'page_in']
        self.assertEqual(loaded, ['p00', 'p11'])
        self.assertEqual(trace['selected_tool'], 'p11:op0')

    def test_wrong_valid_tool_is_not_rejected_by_gold_answer(self):
        request = RuntimeRequest(self.pages['p11']['tools'][0]['query'], 'p00')
        trace = run_episode(ScriptedChooser(['p00:op0']), request, self.pages)
        self.assertEqual(trace['selected_tool'], 'p00:op0')
        case = EvaluationCase('bad', 'wrong_page', request, 'p11', 'p11:op0')
        self.assertFalse(score_episode(case, trace)['success'])
        different_gold = EvaluationCase('changed-label', 'wrong_page', request, 'p00', 'p00:op0')
        self.assertTrue(score_episode(different_gold, trace)['success'])
        self.assertEqual(len(trace['calls']), 1)

    def test_stale_initial_page_cannot_be_used_before_refresh(self):
        request = RuntimeRequest(self.pages['p00']['tools'][0]['query'], 'p00', True)
        chooser = ScriptedChooser(['PAGE:p00', 'p00:op0'])
        trace = run_episode(chooser, request, self.pages)
        self.assertEqual(trace['events'][0], {'event': 'stale_block', 'page': 'p00'})
        self.assertEqual(trace['calls'][0]['stage'], 'directory')
        self.assertEqual(trace['selected_tool'], 'p00:op0')

    def test_clarify_terminates_and_budget_bounds_next(self):
        trace = run_episode(ScriptedChooser(['CLARIFY']), RuntimeRequest('unclear'), self.pages)
        self.assertEqual(trace['terminal'], 'clarify')
        self.assertEqual(len(trace['calls']), 1)
        trace = run_episode(ScriptedChooser(['NEXT'] * 3), RuntimeRequest('browse'), self.pages, max_calls=3)
        self.assertEqual(trace['terminal'], 'directory_exhausted')
        self.assertIsNone(trace['selected_tool'])
        self.assertEqual(trace['directory_windows_visited'], trace['directory_window_count'])
        self.assertTrue(any(e['event'] == 'directory_exhausted' for e in trace['events']))

    def test_fixed_resident_has_no_page_escape(self):
        chooser = ScriptedChooser(['STOP'])
        request = RuntimeRequest('some request', 'p00')
        trace = run_episode(chooser, request, self.pages, allow_paging=False)
        self.assertNotIn('PAGE', [o.option_id for o in chooser.calls[0][1]])
        self.assertEqual(trace['terminal'], 'stop')

    def test_verification_rejection_reenters_paging(self):
        request = RuntimeRequest(self.pages['p11']['tools'][0]['query'], 'p00')
        chooser = ScriptedChooser(['p00:op0', 'PAGE', 'NEXT', 'NEXT', 'PAGE:p11', 'p11:op0', 'ACCEPT'])
        trace = run_episode(chooser, request, self.pages, verify_candidate=True)
        self.assertEqual(trace['selected_tool'], 'p11:op0')
        self.assertIn('candidate_rejected', [e['event'] for e in trace['events']])
        self.assertLessEqual(trace['submitted_choice_peak'], 8)

    def test_verification_accepts_wrong_candidate_without_oracle_veto(self):
        request = RuntimeRequest(self.pages['p11']['tools'][0]['query'], 'p00')
        chooser = ScriptedChooser(['p00:op0', 'ACCEPT'])
        trace = run_episode(chooser, request, self.pages, verify_candidate=True)
        self.assertEqual(trace['selected_tool'], 'p00:op0')
        case = EvaluationCase('bad-accept', 'wrong_page', request, 'p11', 'p11:op0')
        self.assertFalse(score_episode(case, trace)['success'])


if __name__ == '__main__':
    unittest.main()
