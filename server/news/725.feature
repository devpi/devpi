fix #725: new option ``mirror_whitelist_inheritance`` for indexes.
The ``union`` setting is the old behaviour and used for existing indexes to not break existing installations.
With it the whitelist of each index in the inheritance order is merged into the current whitelist.
This could lead to unexpected whitelisting.
The new ``intersection`` setting is used for all new indexes and it intersects the whitelist at each step in the inheritance order which is more secure and never causes unexpected whitelisting.