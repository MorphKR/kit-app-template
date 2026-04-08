```{csv-table}
**Extension**: {{ extension_version }},**Documentation Generated**: {sub-ref}`today`
```

# Settings

## Settings Provided by the Extension
### exts."morph.hytwin_section_extension".menuPath
   - **Default Value**: Tools/Section
   - **Description**: Specifies the menu path where the Section Tool window is inserted within the UI.

### exts."morph.hytwin_section_extension".useSessionLayer
   - **Default Value**: True
   - **Description**: Determines whether section editing operations use the session layer of the USD stage.

### exts."morph.hytwin_section_extension".alwaysDisplay
   - **Default Value**: False
   - **Description**: Controls whether the Section Tool window is always displayed irrespective of automatic UI visibility behaviors.

## Settings Used by the Extension but Provided by Another Extension
### CURRENT_TOOL_PATH
   - **Description**: Specifies the path of the currently active tool, enabling the extension to check and switch tool modes when window visibility changes.

### SETTING_SECTION_ENABLED
   - **Description**: Determines if the section tool is activated on stage, allowing the extension to disable section operations when a stage is opened.

### SETTING_SECTION_LIGHT
   - **Description**: Indicates whether section lighting is enabled, affecting how the section is rendered visually in the viewport.

### SETTING_SECTION_DIRECTION
   - **Description**: Specifies the default cutting direction for sections, thereby controlling the orientation for the section plane.

### SETTING_SECTION_PLANE
   - **Description**: Defines the section plane via a float array representing its equation; this value is updated in response to tool transform changes.

### SETTING_SECTION_MANIPULATOR
   - **Description**: Controls the visibility of the section manipulator widget, allowing users to interactively adjust the section settings.

### SETTING_RTX_DEFAULT_SECTION_DIRECTION
   - **Description**: Provides the fallback section cutting direction used in RTX workflows, ensuring consistency when no user setting is specified.

### SETTING_RTX_DEFAULT_SECTION_MANIPULATOR
   - **Description**: Specifies the default state of the section manipulator in RTX mode, serving as a baseline configuration for the UI control.

### /exts/omni.kit.window.viewport/showContextMenu
   - **Description**: Manages the visibility of the viewport context menu based on persistent application settings provided by another extension.

### /app/transform/operation
   - **Description**: Controls the current transform operation mode (e.g., "move"), which determines how transformation commands are applied within the application.

### SETTING_SECTION_ALWAYS_DISPLAY
   - **Description**: Determines whether the section tool window remains visible at all times, overriding normal UI show/hide behavior.

