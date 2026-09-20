import pcbnew, os
d = os.path.dirname(os.path.abspath(__file__))
b = pcbnew.LoadBoard(os.path.join(d, "esp32-4to20ma-board.kicad_pcb"))
n0 = len(list(b.GetTracks()))
ok = pcbnew.ImportSpecctraSES(b, os.path.join(d, "esp32-4to20ma-board.ses"))
print("import ok:", ok, "tracks before/after:", n0, len(list(b.GetTracks())))
