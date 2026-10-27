-- Generated from schema.py. Do not edit by hand.
PRAGMA foreign_keys = ON;

CREATE TABLE sku (
  sku_id TEXT NOT NULL,
  sku_name TEXT NOT NULL,
  category TEXT NOT NULL CHECK (category IN ('ELEC', 'MECH', 'PACK', 'RAW')),
  uom TEXT NOT NULL CHECK (uom IN ('EA', 'BOX', 'KG')),
  unit_cost REAL NOT NULL,
  is_make INTEGER NOT NULL,
  PRIMARY KEY (sku_id)
);

CREATE TABLE location (
  location_id TEXT NOT NULL,
  location_name TEXT NOT NULL,
  location_type TEXT NOT NULL CHECK (location_type IN ('PLANT', 'DC', 'STORE')),
  region TEXT NOT NULL CHECK (region IN ('NORTH', 'SOUTH', 'EAST', 'WEST')),
  PRIMARY KEY (location_id)
);

CREATE TABLE supplier (
  supplier_id TEXT NOT NULL,
  supplier_name TEXT NOT NULL,
  region TEXT NOT NULL CHECK (region IN ('IN', 'CN', 'DE', 'US', 'MX')),
  reliability REAL NOT NULL,
  is_constrained INTEGER NOT NULL,
  PRIMARY KEY (supplier_id)
);

CREATE TABLE uom_conversion (
  from_uom TEXT NOT NULL CHECK (from_uom IN ('EA', 'BOX', 'KG', 'LB')),
  to_uom TEXT NOT NULL CHECK (to_uom IN ('EA', 'BOX', 'KG', 'LB')),
  factor REAL NOT NULL,
  PRIMARY KEY (from_uom, to_uom)
);

CREATE TABLE sku_substitute (
  sku_id TEXT NOT NULL,
  substitute_sku_id TEXT NOT NULL,
  approval_status TEXT NOT NULL CHECK (approval_status IN ('APPROVED', 'PENDING', 'REJECTED')),
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  PRIMARY KEY (sku_id, substitute_sku_id),
  FOREIGN KEY (sku_id) REFERENCES sku (sku_id),
  FOREIGN KEY (substitute_sku_id) REFERENCES sku (sku_id)
);

CREATE TABLE bom (
  parent_sku_id TEXT NOT NULL,
  component_sku_id TEXT NOT NULL,
  qty_per INTEGER NOT NULL,
  PRIMARY KEY (parent_sku_id, component_sku_id),
  FOREIGN KEY (parent_sku_id) REFERENCES sku (sku_id),
  FOREIGN KEY (component_sku_id) REFERENCES sku (sku_id)
);

CREATE TABLE lead_time (
  sku_id TEXT NOT NULL,
  supplier_id TEXT NOT NULL,
  lead_time_days INTEGER NOT NULL,
  moq INTEGER NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  PRIMARY KEY (sku_id, supplier_id),
  FOREIGN KEY (sku_id) REFERENCES sku (sku_id),
  FOREIGN KEY (supplier_id) REFERENCES supplier (supplier_id)
);

CREATE TABLE supplier_capacity (
  supplier_id TEXT NOT NULL,
  week TEXT NOT NULL,
  week_start TEXT NOT NULL,
  capacity_units INTEGER NOT NULL,
  PRIMARY KEY (supplier_id, week),
  FOREIGN KEY (supplier_id) REFERENCES supplier (supplier_id)
);

CREATE TABLE production_capacity (
  location_id TEXT NOT NULL,
  week TEXT NOT NULL,
  week_start TEXT NOT NULL,
  capacity_units INTEGER NOT NULL,
  PRIMARY KEY (location_id, week),
  FOREIGN KEY (location_id) REFERENCES location (location_id)
);

CREATE TABLE forecast_demand (
  demand_id TEXT NOT NULL,
  sku_id TEXT NOT NULL,
  location_id TEXT NOT NULL,
  week TEXT NOT NULL,
  week_start TEXT NOT NULL,
  forecast_qty INTEGER NOT NULL,
  PRIMARY KEY (demand_id),
  UNIQUE (sku_id, location_id, week),
  FOREIGN KEY (sku_id) REFERENCES sku (sku_id),
  FOREIGN KEY (location_id) REFERENCES location (location_id)
);

CREATE TABLE inventory (
  inventory_id TEXT NOT NULL,
  sku_id TEXT NOT NULL,
  location_id TEXT NOT NULL,
  snapshot_date TEXT NOT NULL,
  on_hand_qty INTEGER NOT NULL,
  safety_stock_qty INTEGER NOT NULL,
  PRIMARY KEY (inventory_id),
  UNIQUE (sku_id, location_id),
  FOREIGN KEY (sku_id) REFERENCES sku (sku_id),
  FOREIGN KEY (location_id) REFERENCES location (location_id)
);

CREATE TABLE purchase_order (
  po_id TEXT NOT NULL,
  sku_id TEXT NOT NULL,
  supplier_id TEXT NOT NULL,
  location_id TEXT NOT NULL,
  order_date TEXT NOT NULL,
  promised_date TEXT NOT NULL,
  expected_arrival_date TEXT NOT NULL,
  qty_ordered INTEGER NOT NULL,
  order_uom TEXT NOT NULL CHECK (order_uom IN ('EA', 'BOX', 'KG', 'LB')),
  qty_base INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('PLANNED', 'CONFIRMED', 'SHIPPED', 'DELAYED', 'CANCELLED')),
  transport_delay_days INTEGER NOT NULL,
  po_value REAL NOT NULL,
  PRIMARY KEY (po_id),
  FOREIGN KEY (sku_id) REFERENCES sku (sku_id),
  FOREIGN KEY (supplier_id) REFERENCES supplier (supplier_id),
  FOREIGN KEY (location_id) REFERENCES location (location_id),
  FOREIGN KEY (sku_id, supplier_id) REFERENCES lead_time (sku_id, supplier_id),
  FOREIGN KEY (sku_id, location_id) REFERENCES inventory (sku_id, location_id)
);

CREATE TABLE po_event (
  po_id TEXT NOT NULL,
  event_seq INTEGER NOT NULL,
  event_type TEXT NOT NULL CHECK (event_type IN ('PLANNED', 'CONFIRMED', 'SHIPPED', 'DELAYED', 'CANCELLED')),
  event_date TEXT NOT NULL,
  PRIMARY KEY (po_id, event_seq),
  FOREIGN KEY (po_id) REFERENCES purchase_order (po_id)
);

CREATE TABLE production_plan (
  plan_id TEXT NOT NULL,
  sku_id TEXT NOT NULL,
  location_id TEXT NOT NULL,
  week TEXT NOT NULL,
  week_start TEXT NOT NULL,
  planned_qty INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('PLANNED', 'RELEASED')),
  PRIMARY KEY (plan_id),
  UNIQUE (sku_id, location_id, week),
  FOREIGN KEY (sku_id) REFERENCES sku (sku_id),
  FOREIGN KEY (location_id) REFERENCES location (location_id),
  FOREIGN KEY (sku_id, location_id) REFERENCES inventory (sku_id, location_id)
);

CREATE TABLE production_component_requirement (
  plan_id TEXT NOT NULL,
  component_sku_id TEXT NOT NULL,
  required_qty INTEGER NOT NULL,
  PRIMARY KEY (plan_id, component_sku_id),
  FOREIGN KEY (plan_id) REFERENCES production_plan (plan_id),
  FOREIGN KEY (component_sku_id) REFERENCES sku (sku_id)
);

CREATE TABLE projected_balance (
  sku_id TEXT NOT NULL,
  location_id TEXT NOT NULL,
  week TEXT NOT NULL,
  opening_qty INTEGER NOT NULL,
  forecast_qty INTEGER NOT NULL,
  po_receipts_qty INTEGER NOT NULL,
  production_qty INTEGER NOT NULL,
  closing_qty INTEGER NOT NULL,
  PRIMARY KEY (sku_id, location_id, week),
  FOREIGN KEY (sku_id, location_id) REFERENCES inventory (sku_id, location_id)
);

CREATE TABLE shortage (
  shortage_id TEXT NOT NULL,
  sku_id TEXT NOT NULL,
  location_id TEXT NOT NULL,
  first_week TEXT NOT NULL,
  need_date TEXT NOT NULL,
  end_week TEXT NOT NULL,
  weeks_affected INTEGER NOT NULL,
  shortage_qty INTEGER NOT NULL,
  value_at_risk REAL NOT NULL,
  cause_code TEXT NOT NULL CHECK (cause_code IN ('TRANSPORT_DELAY', 'SUPPLIER_CAPACITY', 'PRODUCTION_CAPACITY', 'DEMAND_SPIKE', 'PO_CANCELLED', 'LEAD_TIME_GAP', 'NO_INBOUND_PLANNED', 'INSUFFICIENT_SUPPLY')),
  cause_detail TEXT NOT NULL,
  lead_time_days_used INTEGER NOT NULL,
  latest_order_date TEXT NOT NULL,
  ordering_window_open INTEGER NOT NULL,
  priority_score REAL NOT NULL,
  priority_rank INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('OPEN', 'MITIGATION_PROPOSED', 'ESCALATED')),
  PRIMARY KEY (shortage_id),
  UNIQUE (sku_id, location_id, first_week),
  FOREIGN KEY (sku_id, location_id) REFERENCES inventory (sku_id, location_id)
);

CREATE TABLE mitigation_option (
  mitigation_id TEXT NOT NULL,
  shortage_id TEXT NOT NULL,
  option_type TEXT NOT NULL CHECK (option_type IN ('ALT_SUPPLIER', 'EXPEDITE_PO', 'SUBSTITUTE', 'PRODUCTION_BOOST')),
  supplier_id TEXT,
  substitute_sku_id TEXT,
  source_po_id TEXT,
  recovery_qty INTEGER NOT NULL,
  lead_time_days INTEGER NOT NULL,
  recovery_week TEXT NOT NULL,
  extra_cost REAL NOT NULL,
  cost_per_unit REAL NOT NULL,
  service_level_pct REAL NOT NULL,
  resolves_shortage INTEGER NOT NULL,
  recommended INTEGER NOT NULL,
  PRIMARY KEY (mitigation_id),
  FOREIGN KEY (shortage_id) REFERENCES shortage (shortage_id),
  FOREIGN KEY (supplier_id) REFERENCES supplier (supplier_id),
  FOREIGN KEY (substitute_sku_id) REFERENCES sku (sku_id),
  FOREIGN KEY (source_po_id) REFERENCES purchase_order (po_id)
);
