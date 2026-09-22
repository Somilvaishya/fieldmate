import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, today


class FieldMateChecklistTemplate(Document):
	"""A set of questions a rep answers at a shop.

	Templates get edited - a question is reworded, another is dropped. Answers already captured
	must keep meaning what they meant, so every answer row carries the version it was asked under
	and this controller bumps that version whenever the questions actually change.
	"""

	def validate(self):
		self.set_defaults()
		self.validate_codes()
		self.validate_ranges()
		self.validate_branching()
		self.bump_version()
		self.question_count = len(self.questions)

	def set_defaults(self):
		if not self.effective_from:
			self.effective_from = today()
		if not cint(self.version):
			self.version = 1
		for index, row in enumerate(self.questions, start=1):
			if not cint(row.sequence):
				row.sequence = index

	def validate_codes(self):
		"""Codes are how answers are matched back to questions, so they must be unique and stable."""
		seen = {}
		for row in self.questions:
			if not row.question_code:
				frappe.throw(
					frappe._("Row {0}: every question needs a code. Answers are matched to "
					         "questions by code, not by wording.").format(row.idx)
				)
			code = row.question_code.strip()
			if code in seen:
				frappe.throw(
					frappe._("Rows {0} and {1} both use the code {2}. One answer cannot belong "
					         "to two questions.").format(seen[code], row.idx, frappe.bold(code))
				)
			seen[code] = row.idx
			row.question_code = code

	def validate_ranges(self):
		for row in self.questions:
			if row.answer_type in ("Single Choice", "Multi Choice") and not (row.options or "").strip():
				frappe.throw(
					frappe._("Row {0}: a choice question with no options cannot be answered.")
					.format(row.idx)
				)
			if row.min_value is None or row.max_value is None:
				continue
			if flt(row.min_value) > flt(row.max_value):
				frappe.throw(
					frappe._("Row {0}: the minimum ({1}) is above the maximum ({2}).")
					.format(row.idx, row.min_value, row.max_value)
				)

	def validate_branching(self):
		"""A question can only depend on one asked before it, or the rep sees a dead branch."""
		position = {row.question_code: cint(row.sequence) for row in self.questions}
		for row in self.questions:
			parent = (row.depends_on_code or "").strip()
			if not parent:
				continue
			if parent not in position:
				frappe.throw(
					frappe._("Row {0} depends on {1}, which is not a question in this template.")
					.format(row.idx, frappe.bold(parent))
				)
			if position[parent] >= cint(row.sequence):
				frappe.throw(
					frappe._("Row {0} depends on {1}, which comes later in the list. A rep cannot "
					         "answer a question whose trigger has not been asked yet.")
					.format(row.idx, frappe.bold(parent))
				)

	def bump_version(self):
		"""Raise the version only when the questions themselves changed.

		Renaming the template or narrowing its territory does not change what was asked, so it
		must not orphan the answers already recorded under the current version.
		"""
		if self.is_new():
			return

		before = self.get_doc_before_save()
		if not before:
			return
		if self.fingerprint() != self.fingerprint(before):
			self.version = cint(before.version) + 1

	def fingerprint(self, doc=None) -> tuple:
		doc = doc or self
		return tuple(
			(q.question_code, q.question, q.answer_type, (q.options or "").strip(),
			 cint(q.is_required), cint(q.sequence), q.depends_on_code, q.depends_on_value)
			for q in doc.questions
		)
