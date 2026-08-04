# -*- coding: utf-8 -*-

from pathlib import Path
from types import SimpleNamespace
import math
import unittest

import FreeCAD as App

import FSAliases
import FastenersCmd
import FSutils
import ScrewMaker


CATALOG_DIMENSIONS = {
    "M2": (0.4, 3.73, 3.07, 3.23, (3.18, 4.0), (3.94, 4.76)),
    "M2.5": (0.45, 4.55, 3.86, 4.01, (5.74,), (6.50,)),
    "M3": (0.5, 4.55, 3.86, 4.01, (3.43, 5.74), (4.19, 6.50)),
    "M3.5": (0.6, 5.33, 4.65, 4.81, (7.14,), (7.90,)),
    "M4": (0.7, 6.17, 5.51, 5.67, (4.70, 8.15), (5.46, 8.91)),
    "M5": (0.8, 6.93, 6.27, 6.43, (5.72, 9.52), (6.48, 10.28)),
    "M6": (1.0, 8.69, 7.87, 8.03, (7.62, 12.70), (8.38, 13.46)),
    "M8": (1.25, 10.31, 9.50, 9.60, (12.70,), (13.46,)),
}


class TestStandardHeatInsertCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = App.newDocument("StandardHeatInsertTests")

    @classmethod
    def tearDownClass(cls):
        App.closeDocument(cls.document.Name)

    def test_catalog_matches_pennengineering_metric_iut_table(self):
        catalog_file = (
            Path(__file__).resolve().parents[1] / "FsData" / "HeatInserts.csv"
        )
        tables = FSutils.csv2dict(str(catalog_file), "unused")

        self.assertEqual(set(tables["PEMIUTBdef"]), set(CATALOG_DIMENSIONS))
        for diameter, specification in CATALOG_DIMENSIONS.items():
            pitch, outer, body, hole, lengths, depths = specification
            row = tables["PEMIUTBdef"][diameter]
            self.assertEqual(row[:4], (pitch, outer, body, hole))
            self.assertEqual(
                row[4:],
                (0.13, 0.23, 0.13, 0.08, 0.0, "6H, ASME B1.13M"),
            )
            self.assertEqual(
                tuple(float(value) for value in tables["PEMIUTBlength"][diameter]),
                lengths,
            )
            for length, depth in zip(lengths, depths):
                key = f"{diameter}x{length:g}"
                self.assertEqual(tables["PEMIUTBinstall"][key][0], depth)

    def test_material_variants_share_only_the_exact_geometry_catalog(self):
        for insert_type in ("PEMIUTA", "PEMIUTB", "PEMIUTC"):
            self.assertEqual(
                FSAliases.FSGetTypeAlias(insert_type),
                "PEMIUTB",
            )
            self.assertEqual(
                FSAliases.FSGetIconAlias(insert_type),
                "IUTHeatInsert",
            )
            self.assertTrue(
                (
                    Path(FastenersCmd.iconPath)
                    / f"{FSAliases.FSGetIconAlias(insert_type)}.svg"
                ).is_file()
            )
            self.assertEqual(
                ScrewMaker.screwTables[insert_type],
                ScrewMaker.screwTables["PEMIUTB"],
            )
            self.assertTrue(
                FastenersCmd.FSGetDescription(insert_type).startswith(
                    "PennEngineering SI"
                )
            )
            self.assertNotIn(
                "LeftHanded",
                FastenersCmd.FSGetParams(insert_type),
            )

    def test_native_fastener_object_exposes_only_valid_catalog_choices(self):
        obj = self.document.addObject(
            "PartDesign::FeaturePython",
            "PennEngineeringHeatInsert",
        )
        FastenersCmd.FSScrewObject(obj, "PEMIUTB", None)
        obj.Diameter = "M4"
        self.document.recompute()

        self.assertEqual(obj.Type, "PEMIUTB")
        self.assertEqual(
            list(obj.getEnumerationsOfProperty("Diameter")),
            ["Auto", "M2", "M2.5", "M3", "M3.5", "M4", "M5", "M6", "M8"],
        )
        self.assertEqual(
            list(obj.getEnumerationsOfProperty("Length")),
            ["4.7", "8.15"],
        )
        self.assertTrue(obj.Shape.isValid())
        self.assertEqual(len(obj.Shape.Solids), 1)

    def test_auto_diameter_matches_the_manufacturer_installation_hole(self):
        hole = SimpleNamespace(Curve=SimpleNamespace(Radius=2.85))
        self.assertEqual(
            ScrewMaker.Instance.AutoDiameter("PEMIUTB", hole),
            "M4",
        )

    def test_every_size_and_length_is_a_valid_renderable_solid(self):
        maker = ScrewMaker.Instance
        for detailed_thread in (False, True):
            for diameter, specification in CATALOG_DIMENSIONS.items():
                _pitch, expected_outer, _body, _hole, lengths, _depths = specification
                for length in lengths:
                    with self.subTest(
                        detailed_thread=detailed_thread,
                        diameter=diameter,
                        length=length,
                    ):
                        attributes = SimpleNamespace(
                            Type="PEMIUTB",
                            baseType="PEMIUTB",
                            Diameter=diameter,
                            calc_diam=diameter,
                            calc_len=f"{length:g}",
                            LeftHanded=False,
                            Thread=detailed_thread,
                        )
                        shape = maker.createFastener(attributes)
                        self.assertFalse(shape.isNull())
                        self.assertTrue(shape.isValid())
                        self.assertEqual(len(shape.Solids), 1)
                        self.assertGreater(shape.Volume, 0.0)

                        bounds = shape.optimalBoundingBox(False, False)
                        self.assertTrue(
                            math.isclose(
                                bounds.XLength,
                                expected_outer,
                                abs_tol=3.0e-6,
                            )
                        )
                        self.assertTrue(
                            math.isclose(
                                bounds.YLength,
                                expected_outer,
                                abs_tol=3.0e-6,
                            )
                        )
                        self.assertTrue(
                            math.isclose(bounds.ZLength, length, abs_tol=3.0e-6)
                        )

                        vertices, triangles = shape.tessellate(0.08)
                        self.assertGreater(len(vertices), 0)
                        self.assertGreater(len(triangles), 0)
                        self.assertTrue(
                            all(
                                math.isfinite(coordinate)
                                for vertex in vertices
                                for coordinate in (vertex.x, vertex.y, vertex.z)
                            )
                        )


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        TestStandardHeatInsertCatalog
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
