"""Reading a distributor's secondary sales file.

Gate 5 criterion 1 is the shape of this whole module: *a file with 3 bad rows imports the good
rows and reports the 3 with row numbers and reasons.* A distributor who has to fix and resend a
whole file over three lines stops sending files, and then there is no secondary sales data at
all — which is the one thing this phase exists to produce.

The parsing tests need no database at all. They are the ones that will be run again and again
when a real distributor's export arrives and does something nobody expected.
"""

import frappe

from fieldmate.services import secondary_sales as importer
from fieldmate.tests.base import FieldMateTestCase
from fieldmate.tests.test_stock import StockFixture


class TestReadingHeaders(FieldMateTestCase):
	"""No two distributors export the same header, and none will change theirs for us."""

	def test_the_standard_names_are_understood_without_being_told(self):
		mapping, unknown = importer.build_mapping(["Date", "Item Code", "Qty", "Amount"])
		self.assertEqual(mapping["date"], 0)
		self.assertEqual(mapping["item_code"], 1)
		self.assertEqual(mapping["qty"], 2)
		self.assertEqual(mapping["amount"], 3)
		self.assertEqual(unknown, [])

	def test_case_spacing_and_punctuation_do_not_matter(self):
		""""Item Code", "item_code" and "ITEM-CODE" are the same column. Arguing about it helps
		nobody."""
		mapping, _ = importer.build_mapping(["SALE_DATE", "item-code", "  Quantity  "])
		self.assertEqual(mapping["date"], 0)
		self.assertEqual(mapping["item_code"], 1)
		self.assertEqual(mapping["qty"], 2)

	def test_a_distributors_own_names_are_configured_rather_than_coded(self):
		mapping, unknown = importer.build_mapping(
			["Bill Dt", "Material", "Nos"],
			overrides={"Bill Dt": "date", "Material": "item_code", "Nos": "qty"},
		)
		self.assertEqual(sorted(mapping), ["date", "item_code", "qty"])
		self.assertEqual(unknown, [])

	def test_a_column_we_cannot_place_is_named_rather_than_ignored(self):
		"""A distributor whose quantity column is called "Pcs." deserves to be told that is why
		nothing imported, instead of being handed an empty document."""
		_, unknown = importer.build_mapping(["Date", "Item Code", "Qty", "Scheme Rebate"])
		self.assertEqual(unknown, ["Scheme Rebate"])

	def test_excels_utf8_bom_does_not_eat_the_first_column(self):
		"""Saving as "CSV UTF-8" writes a BOM, which otherwise turns Date into ﻿Date and
		makes the date column vanish for no visible reason."""
		headers, rows = importer.read_rows("﻿Date,Item Code,Qty\n2026-09-01,X,1\n".encode())
		self.assertEqual(headers[0], "Date")
		self.assertEqual(len(rows), 1)


class TestReadingRows(StockFixture):
	def csv(self, *rows, header="Date,Item Code,Qty,Amount,Shop Name"):
		return "\n".join([header, *rows])

	def parse(self, text):
		return importer.parse(text, self.distributor.name)

	def test_a_good_file_reads_clean(self):
		result = self.parse(self.csv(f"2026-09-01,{self.item},12,1464,Sharma Kirana"))
		self.assertEqual(result["rejected"], [])
		line = result["lines"][0]
		self.assertEqual(line["item_code"], self.item)
		self.assertEqual(line["qty"], 12)
		self.assertEqual(line["amount"], 1464)
		self.assertEqual(line["retailer_name"], "Sharma Kirana")

	def test_three_bad_rows_do_not_cost_the_good_ones(self):
		"""Gate 5 criterion 1, exactly as written."""
		result = self.parse(self.csv(
			f"2026-09-01,{self.item},12,1464,Sharma Kirana",     # row 2, good
			"2026-09-01,NOT-A-REAL-ITEM,5,600,Verma Stores",     # row 3, unknown item
			f"2026-09-02,{self.item},abc,100,Gupta Kirana",      # row 4, qty not a number
			f"2026-09-03,{self.item},7,840,Singh Provisions",    # row 5, good
			f"not-a-date,{self.item},3,360,Rao Stores",           # row 6, bad date
			f"2026-09-04,{self.item},2,240,Iyer Mart",            # row 7, good
		))

		self.assertEqual(len(result["lines"]), 3, "every good row imports")
		self.assertEqual([r["row"] for r in result["rejected"]], [3, 4, 6],
		                 "and each bad one is named by its row number in the file")
		reasons = " ".join(r["reason"] for r in result["rejected"])
		self.assertIn("NOT-A-REAL-ITEM", reasons)
		self.assertIn("abc", reasons)
		self.assertIn("not-a-date", reasons)

	def test_the_row_numbers_match_what_a_person_sees_in_the_spreadsheet(self):
		"""Row 1 is the header, and somebody counting rows in Excel starts at 1. Reporting a
		zero-based offset sends them to the wrong line."""
		result = self.parse(self.csv("2026-09-01,NOPE,1,10,A shop"))
		self.assertEqual(result["rejected"][0]["row"], 2)

	def test_a_thousands_separator_does_not_turn_1200_into_1(self):
		"""Indian exports carry them routinely, and a stray comma would quietly lose 99% of a
		line."""
		result = self.parse(self.csv(f"2026-09-01,{self.item},\"1,200\",\"1,46,400\",Big Bazaar"))
		self.assertEqual(result["lines"][0]["qty"], 1200)
		self.assertEqual(result["lines"][0]["amount"], 146400)

	def test_a_sale_of_nothing_is_not_a_sale(self):
		result = self.parse(self.csv(f"2026-09-01,{self.item},0,0,Empty Stores"))
		self.assertEqual(result["lines"], [])
		self.assertIn("not a sale", result["rejected"][0]["reason"])

	def test_a_file_missing_a_required_column_says_which_one(self):
		result = self.parse(self.csv(f"2026-09-01,{self.item}", header="Date,Item Code"))
		self.assertEqual(result["lines"], [])
		self.assertIn("qty", result["rejected"][0]["reason"])

	def test_an_empty_file_is_reported_rather_than_imported_as_nothing(self):
		result = self.parse("")
		self.assertIn("empty", result["rejected"][0]["reason"].lower())

	def test_a_shop_we_can_match_is_matched_and_one_we_cannot_is_not_an_error(self):
		"""Most distributors have no shop id in common with us at all. A blank match is normal."""
		result = self.parse(self.csv(
			f"2026-09-01,{self.item},5,610,{self.outlet.outlet_name}",
			f"2026-09-01,{self.item},5,610,Some Shop We Have Never Heard Of",
		))
		self.assertEqual(result["rejected"], [])
		self.assertEqual(result["lines"][0]["outlet"], self.outlet.name)
		self.assertIsNone(result["lines"][1]["outlet"])
		self.assertEqual(result["lines"][1]["retailer_name"], "Some Shop We Have Never Heard Of",
		                 "kept verbatim, because next quarter somebody will ask which shop it was")


class TestImportingAFile(StockFixture):
	def test_the_document_carries_both_counts_and_every_rejection(self):
		"""A file that imports 340 of 347 rows and says nothing about the other 7 is worse than
		one that fails outright, because nobody goes looking."""
		text = "\n".join([
			"Date,Item Code,Qty",
			f"2026-09-01,{self.item},10",
			"2026-09-01,GHOST-SKU,4",
			f"2026-09-02,{self.item},6",
		])
		result = importer.import_file(self.distributor.name, text, "2026-09-01", "2026-09-30",
		                             file_name="sept.csv")

		doc = frappe.get_doc("FieldMate Secondary Sales", result["name"])
		self.track("FieldMate Secondary Sales", doc.name)

		self.assertEqual(doc.rows_read, 3)
		self.assertEqual(doc.rows_rejected, 1)
		self.assertEqual(doc.total_lines, 2)
		self.assertEqual(doc.total_qty, 16)
		self.assertIn("Row 3", doc.rejections)
		self.assertIn("GHOST-SKU", doc.rejections)

	def test_importing_produces_no_gl_entry(self):
		"""Gate 5 criterion 4. These are the distributor's sales; we were never a party to them."""
		before = frappe.db.count("GL Entry")
		text = f"Date,Item Code,Qty\n2026-09-01,{self.item},10\n"
		result = importer.import_file(self.distributor.name, text, "2026-09-01", "2026-09-30")
		self.track("FieldMate Secondary Sales", result["name"])

		self.assertEqual(frappe.db.count("GL Entry"), before,
		                 "no secondary sales document produces a GL Entry")

	def test_a_file_nothing_could_be_read_from_is_refused_with_the_reason(self):
		"""Creating an empty document would look like a successful import of a month of zero
		sales, which is a figure somebody would then act on."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			importer.import_file(self.distributor.name, "Date,Item Code,Qty\n2026-09-01,GHOST,1\n",
			                     "2026-09-01", "2026-09-30")
		self.assertIn("GHOST", str(ctx.exception))
