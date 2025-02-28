import pandas as pd
import json
from datetime import datetime
from typing import Dict, Any, Optional, Union, List
import types
from .TrackedWell import TrackedWell


class Plate:
    """Tracks samples, locations, and volumes in a plate."""
    
    def __init__(self, plate_type="96-well", file_path=None, max_vol=None):

        self.data = {}
        self.plate_data = {}
        self.well_data = {}
        self.required_keys = {"well_data","plate_data"}
        self.required_keys_wells = {"volume"}
        self.required_keys_plate = {'plate_type', 'total_wells', 'max_volume'}
        self.physical_labware = None
        
        if file_path:
            try:
                self.load_plate_from_json(file_path)
                self.well_data = self.data["well_data"]
                self.plate_data = self.data["plate_data"]
                
            except ValueError as e:
                print(f"Error: {e}")
                print("The plate could not be loaded from indicated path, make sure it points to a json file with the correct format")

        else:

            self.init_empty_plate(plate_type, max_vol)

    
    def load_plate_from_json(self, file_path):
        """Load plate data from a JSON file."""
        with open(file_path, mode='r') as jsonfile:
            self.data = json.load(jsonfile)

        # Check if top-level required keys are present
        if not self.required_keys.issubset(self.data.keys()):
            missing_keys = self.required_keys - set(self.data.keys())
            raise ValueError(f"JSON file is missing required top-level keys: {missing_keys}")

        # Check if plate_data contains correctly structured well entries
        if not isinstance(self.data["plate_data"], dict):
            raise ValueError("'plate_data' should be a dictionary mapping well positions to data.")


        # Check if well_data contains correctly structured well entries
        if not isinstance(self.data["well_data"], dict):
            raise ValueError("'well_data' should be a dictionary mapping well positions to data.")
            
        for well, info in self.data["well_data"].items():
            if not self.required_keys_wells.issubset(info.keys()):
                missing_keys = self.required_keys_wells - set(info.keys())
                raise ValueError(f"Well '{well}' is missing required keys: {missing_keys}")


    def init_empty_plate(self, plate_type, max_vol):

        self.plate_data["plate_type"] = plate_type
        
        if plate_type == "96-well":
            self.plate_data["total_wells"] = 384
            if not max_vol:
                self.plate_data["max_volume"] = 200
            well_names = self.generate_well_names(["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P"], range(1,25))
        
        if plate_type == "96-well":
            self.plate_data["total_wells"] = 96
            if not max_vol:
                self.plate_data["max_volume"] = 200
            well_names = self.generate_well_names(["A", "B", "C", "D", "E", "F", "G", "H"], range(1,13))
            
        if plate_type == "48-well":
            self.plate_data["total_wells"] = 48
            if not max_vol:
                self.plate_data["max_volume"] = 400 #To be decided            
            well_names = self.generate_well_names(["A", "B", "C", "D", "E", "F"], range(1,9))

        if plate_type == "24-well":
            self.plate_data["total_wells"] = 24
            if not max_vol:
                self.plate_data["max_volume"] = 1000 #To be decided          
            well_names = self.generate_well_names(["A", "B", "C", "D"], range(1,7))

        if plate_type == "12-well":
            self.plate_data["total_wells"] = 12
            if not max_vol:
                self.plate_data["max_volume"] = 2000 #To be decided           
            well_names = self.generate_well_names(["A", "B", "C"], range(1,5))

        if plate_type == "6-well":
            self.plate_data["total_wells"] = 6
            if not max_vol:
                self.plate_data["max_volume"] = 5000 #To be decided             
            well_names = self.generate_well_names(["A", "B"], range(1,4))

        # Initalize well data        
        for well_name in well_names:
            if well_name not in self.well_data:
                self.well_data[well_name] = {
                    "volume": 0,
                    "name": None,
                }


    def generate_well_names(self, rows, columns):
        well_names = []
        for c in columns:
            for r in rows:
                well_names.append(r + str(c))
        return well_names
            
    def init_from_twist_plate_map(self, file_path):
        """Load well data from a twist plate map."""
        plate_map = pd.read_csv(file_path, index_col="Well Location").to_dict(orient='index')
        
        for well, info in plate_map.items():
            self.well_data[well] = {"sequence": info["Insert Sequence"], "name": info["Name"], "yield": info["Yield (ng)"], "volume": 0}
    
    
    def init_wells_from_csv(self, file_path):
        """Initialise well data from a csv."""
        well_data = pd.read_csv(file_path, index_col="Well").to_dict(orient='index')
        
        # Check if "Wells" contains correctly structured well entries
        for well, info in well_data.items():
            if not self.required_keys_wells.issubset(info.keys()):
                missing_keys = self.required_keys_wells - set(info.keys())
                raise ValueError(f"Well '{well}' is missing required keys: {missing_keys}")

        self.well_data = well_data

   
    def init_wells_from_json(self, file_path):
        """Initialise well data from a json."""
        with open(file_path, mode='r') as jsonfile:
            well_data = json.load(jsonfile)
        
        # Check if "Wells" contains correctly structured well entries
        for well, info in well_data.items():
            if not self.required_keys_wells.issubset(info.keys()):
                missing_keys = self.required_keys_wells - set(info.keys())
                raise ValueError(f"Well '{well}' is missing required keys: {missing_keys}")

        self.well_data = well_data
        self.data["well_data"] = self.well_data


    def resupend_twist_plate(self, final_conc=15):
        """Resuspend a new Twist oligo plate with water to the desired concentration"""
        #Check if all volumes are 0 so the plate was not resupended yet
        if sum([info["volume"] for well, info in self.well_data.items()]) != 0:
            raise ValueError("Twist_pate object was already resupended.")

        else:
            resuspend = {}
            for well, info in self.well_data.items():
                if "yield" in info.keys():
                    vol = info["yield"]/final_conc #Maybe round
                    self.well_data[well]["conc"] = final_conc
                    resuspend[well] = vol

            #Give pipetting command for resupension
            return resuspend


    def link_to_labware(self, physical_labware: Any) -> None:
        """
        Link virtual plate to physical labware on OT-2 deck
        
        Args:
            physical_labware: Opentrons labware object
        """
        # Validate compatibility
        labware_wells = len(physical_labware.wells())
        if labware_wells != self.plate_data['total_wells']:
            raise ValueError(
                f"Labware well count ({labware_wells}) doesn't match "
                f"virtual plate definition ({self.plate_data['total_wells']})"
            )
            
        self.physical_labware = physical_labware
        
        # Initialize any missing wells in well_data
        for well in physical_labware.wells():
            if well.well_name not in self.well_data:
                self.well_data[well.well_name] = {
                    "volume": 0,
                    "name": None,
                }




        def wells(self, *args) -> Union[TrackedWell, List[TrackedWell]]:
            """Get wells in this container
            
            Args:
                *args: string or integer arguments to specify which wells to get
                
            Returns:
                A single wells if only one arg, or a list of wells if multiple args
            """
            if len(args) == 0:
                # Return all wells
                return [TrackedWell(well, self) for well in self.physical_labware.wells()]
            elif len(args) == 1:
                # Return single well
                well = self.physical_labware.wells(args[0])[0]
                return [TrackedWell(well, self)]
            else:
                # Return list of wells
                wells = self.physical_labware.wells(*args)
                return [TrackedWell(well, self) for well in wells]
        
        def wells_by_name(self):
            return {name: TrackedWell(well, self) 
                   for name, well in self.physical_labware.wells_by_name().items()}
        
        # Add wrapped well methods
        self.wells = types.MethodType(wells, self)
        self.wells_by_name = types.MethodType(wells_by_name, self)



        
        # Dinamically assign opentron labware methods on this instance
        
        # Define methods/properties that should not be copied
        excluded_methods = {
            # Tip rack specific methods
            'tip_length', 'set_offset', 'separate_calibration',
            # Well methods,
            'wells', 'wells_by_name'
        }


        attr_name_list = [attr_name for attr_name in dir(physical_labware) if (not attr_name.startswith('_') and attr_name not in excluded_methods)]
        attr_name_list.append('_core')
        

        # Copy safe methods and properties
        for attr_name in attr_name_list:
                
            try:
                attr = getattr(physical_labware, attr_name)
                    
                # Handle different types of attributes
                if isinstance(attr, types.MethodType):
                    # For bound methods
                    def make_method(name):
                        def method(self, *args, **kwargs):
                            return getattr(self.physical_labware, name)(*args, **kwargs)
                        return method
                    setattr(self.__class__, attr_name, make_method(attr_name))
                elif callable(attr):
                    # For regular functions/callables
                    setattr(self, attr_name, attr)

                #elif isinstance(attr, str):
                else:
                    #For strings
                    setattr(self, attr_name, attr)
                        
                        
            except Exception as e:
                print(f"Warning: Could not copy method {attr_name}: {str(e)}")

        
    

    def get_well(self, well_name: str):
        """Get physical well object if linked, otherwise return well data"""
        if self.physical_labware:
            return self.physical_labware.wells_by_name()[well_name]
        elif well_name in self.well_data:
            return self.well_data[well_name]
        else:
            raise KeyError(f"Well {well_name} not found in virtual plate")

    
    def get_volume(self, well_name: str) -> float:
        """Get current volume in specified well"""
        return self.well_data[well_name]["volume"]

    
    def set_volume(self, well_name: str, volume: float) -> None:
        """Set volume for specified well"""
        if volume > self.plate_data['max_volume']:
            raise ValueError(
                f"Volume {volume}µL exceeds maximum well volume "
                f"({self.plate_data['max_volume']}µL)"
            )
        self.well_data[well_name]["volume"] = volume

    
    def add_volume(self, well_name: str, volume: float) -> None:
        """Add volume to specified well"""
        new_volume = self.well_data[well_name]["volume"] + volume
        self.set_volume(well_name, new_volume)

    
    def remove_volume(self, well_name: str, volume: float) -> None:
        """Remove volume from specified well"""
        current_vol = self.well_data[well_name]["volume"]
        if current_vol < volume:
            raise ValueError(
                f"Cannot remove {volume}µL from well {well_name} "
                f"(current volume: {current_vol}µL)"
            )
        self.well_data[well_name]["volume"] -= volume

    
    def get_metadata(self, well_name: str) -> Dict[str, Any]:
        """Get all metadata for specified well"""
        return self.well_data[well_name]

    
    def set_metadata(self, well_name: str, metadata: Dict[str, Any]) -> None:
        """Set metadata for specified well"""
        self.well_data[well_name].update(metadata)

    
    def save_plate(self, output_file: str) -> None:
        """Save current plate and well metadata to JSON file"""
        self.data = {
            'plate_data': self.plate_data,
            'well_data': self.well_data
        }
        with open(output_file, 'w') as f:
            json.dump(self.data, f, indent=2)

    
    def is_linked(self) -> bool:
        """Check if virtual plate is linked to physical labware"""
        return self.physical_labware is not None