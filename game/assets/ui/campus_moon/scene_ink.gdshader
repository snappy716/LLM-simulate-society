shader_type canvas_item;
render_mode unshaded;

// A restrained print-like palette. No screen capture, blur pass, glow or backplate.
uniform float emphasis : hint_range(0.0, 1.0) = 0.0;
varying vec4 vertex_tint;

void vertex() {
	vertex_tint = COLOR;
}

void fragment() {
	vec4 ink = texture(TEXTURE, UV);
	vec2 pixel = TEXTURE_PIXEL_SIZE;
	vec2 under = UV - vec2(0.0, 1.25) * pixel;
	float soft_shadow = (
		texture(TEXTURE, under + vec2(-1.0, -1.0) * pixel).a +
		texture(TEXTURE, under + vec2(1.0, -1.0) * pixel).a +
		texture(TEXTURE, under + vec2(-1.0, 1.0) * pixel).a +
		texture(TEXTURE, under + vec2(1.0, 1.0) * pixel).a
	) * 0.25;
	float light = dot(ink.rgb, vec3(0.2126, 0.7152, 0.0722));
	vec3 paper = mix(vec3(0.78, 0.87, 0.90), vec3(0.92, 0.97, 1.0), emphasis);
	vec3 blue = mix(vec3(0.27, 0.49, 0.61), vec3(0.20, 0.66, 0.93), emphasis);
	vec3 color = light > 0.65 ? paper : (light > 0.24 ? blue : vec3(0.10, 0.23, 0.31));
	float alpha = ink.a * mix(0.86, 1.0, emphasis);
	float shadow_alpha = soft_shadow * (1.0 - alpha) * 0.40;
	float combined = alpha + shadow_alpha;
	vec3 composed = (color * alpha + vec3(0.07, 0.14, 0.19) * shadow_alpha) / max(combined, 0.001);
	COLOR = vec4(composed, combined) * vertex_tint;
}
