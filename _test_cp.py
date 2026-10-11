# -*- coding: utf-8 -*-
import CoolProp.CoolProp as CPC

frac = [77.59, 1.73, 0.0, 0.0, 16.87, 3.81, 0.0]
ids  = [1, 2, 3, 4, 5, 12, 8]
names = {1:'Nitrogen',2:'Oxygen',3:'Hydrogen',4:'CarbonMonoxide',
         5:'CarbonDioxide',6:'CarbonylSulfide',7:'CarbonDisulfide',
         8:'SulfurDioxide',9:'HydrogenSulfide',12:'Water',13:'Methane'}
fl = '&'.join(names[i] for i, f in zip(ids, frac) if f > 0)
z  = [f/100.0 for f in frac if f > 0]
print('fluids:', fl, 'z:', z)
try:
    AS = CPC.AbstractState('HEOS', fl)
    AS.set_mole_fractions(z)
    T = (805.0+745.0)/2.0 + 273.15
    P = 1.0*98066.5
    AS.update(CPC.PT_INPUTS, P, T)
    WM = AS.molar_mass()*1000.0
    print(f"WM={WM:.2f} kg/kmol  rho={AS.rhomass():.4f} kg/m3  cp={AS.cpmass()/1000:.4f} kJ/kgK")
    print(f"mu={AS.viscosity():.3e} Pa.s  k={AS.conductivity():.4f} W/mK  Pr={AS.viscosity()*AS.cpmass()/AS.conductivity():.4f}")
except Exception as e:
    print('MIXTURE FAIL:', type(e).__name__, e)
