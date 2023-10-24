# R Code for Data Transformation and Plotting

## Importing Libraries
library(readxl)
library(ggplot2)
library(car)
library(tidyverse)
library(ggrepel)

setwd("D:/github/R_coding/[사업] 2023_혼합음료/4. 양이온 표시기준 실제값 차이(Log변환)/Na")

## Reading Data
df <- read_excel("Na_data.xlsx")

## Data Transformation
# Transforming Na
df$Transformed_Na <- df$Na - df$Na_max

# Log Transformation
df$Log_Na_max <- log(df$Na_max + 1)
df$Log_Na <- log(df$Na + 1)

# Log Transformed Na
df$Transformed_Log_Na <- df$Log_Na - df$Log_Na_max

## Plotting
# Histogram
ggplot(df, aes(x=Transformed_Na)) +
    geom_histogram(aes(y=..density..), bins=20, alpha=.5) +
    geom_density() +
    ggtitle("Histogram of Transformed_Na")

# QQ-Plot
qqPlot(df$Transformed_Na, main="QQ-Plot of Transformed_Na")

## Adding row numbers
df <- df %>% mutate(row_num = row_number())

## Plotting
ggplot(df, aes(x=row_num, y=Transformed_Log_Na, color=Sample)) +
    geom_point() +
    geom_hline(yintercept=0, linetype="dashed", color = "red") +
    labs(title="Transformed Log Na Values by Sample", x="Index", y="Transformed_Log_Na") +
    theme_minimal()


##ggplot + density

## Removing NaN rows
df <- df %>% drop_na(Transformed_Log_Na)

## ChatGPT
dens_obj <- density(df$Transformed_Log_Na)

# Interpolate density values to match the length of df
# 여기서 보간 방법을 선택해야 합니다. 예를 들어, approx 함수를 사용할 수 있습니다.
interp_dens <- approx(dens_obj$x, dens_obj$y, xout = df$Transformed_Log_Na)$y

# Add interpolated density values to df
df$density <- interp_dens

## Adding row numbers
df <- df %>% mutate(row_num = row_number())

## ChatGPT
ggplot(df, aes(x=row_num, y=Transformed_Log_Na, color=density, shape=Sample)) +
    geom_point() +
    scale_shape_manual(values = c(2, 1)) +
    geom_hline(yintercept=0, linetype="dashed", color = "red") +
    labs(title="Transformed Log Na Values by Sample with Den sity", x="Index", y="Transformed_Log_Na") +
    theme_minimal() +
    scale_colour_gradient(low="blue", high="yellow")


## ChatGPT_완성코드
# 범주를 만드는 예시 코드
df$density_cat <- cut(df$density, breaks = c(-Inf, 0.1, 0.2, 0.3, Inf), labels = c("Very High", "High", "Medium", "Low"))

# ggplot 코드
p <- ggplot(df, aes(x=row_num, y=Transformed_Log_Na, color=density_cat, shape=Sample)) +
    geom_point() +
    scale_shape_manual(values = c(2, 1)) +
    geom_hline(yintercept=0, linetype="dashed", color = "red") +
    geom_hline(yintercept=c(0.5, -0.5), linetype="dashed", color = "#4682B4") +
    labs(title="Transformed Log Na Values by Sample with Density", x="Index", y="Transformed_Log_Na") +
    theme_minimal() +
    scale_colour_manual(values = c("Low" = "#2E8B57", "Medium" = "#FF8C00", "High" = "#D2691E", "Very High" = "#DC143C"))

# 1 이상 또는 -1 이하인 데이터 포인트에 대해 geom_text_repel을 사용합니다.
p + geom_text_repel(
    data = subset(df, Transformed_Log_Na >= 1 | Transformed_Log_Na <= -1),
    aes(label = name_new, color = NULL, shape = NULL),  # color와 shape에 NULL 할당
    box.padding = 0.5,  # 텍스트와 점 사이의 거리를 설정합니다.
    point.padding = 0.5,  # 텍스트와 다른 텍스트 사이의 거리를 설정합니다.
    show.legend = FALSE, # 범례 항목 추가 방지
    segment.color = "black",
    min.segment.length = 0
)

# `Transformed_Log_Na` 값을 기준으로 범주를 만드는 예시 코드
df$density_cat <- cut(df$Transformed_Log_Na, 
                      breaks = c(-Inf, -1.5, -1, -0.5, 0.5, 1, Inf), 
                      labels = c("Very High", "High", "Medium", "Low", "Medium", "High"))

# ggplot 코드
p <- ggplot(df, aes(x=row_num, y=Transformed_Log_Na, color=density_cat, shape=Sample)) +
    geom_point() +
    scale_shape_manual(values = c(2, 1)) +
    geom_hline(yintercept=0, linetype="dashed", color = "red") +
    geom_hline(yintercept=c(0.5, -0.5), linetype="dashed", color = "#4682B4") +
    labs(title="Transformed Log  Values by Part with Density", x="Index", y="Transformed_Log_Na") +
    theme_minimal() +
    scale_colour_manual(values = c("Low" = "#2E8B57", "Medium" = "#FF8C00", "High" = "#D2691E", "Very High" = "#DC143C"))

## 라벨 추가하기
p + geom_text_repel(
    data = subset(df, Transformed_Log_Na >= 1 | Transformed_Log_Na <= -1),
    aes(label = name_new, color = NULL, shape = NULL),
    box.padding = 0.5,
    point.padding = 0.5,
    show.legend = FALSE, # 범례 항목 추가 방지
    segment.color = "black",
    min.segment.length = 0
)

# ggrepel: 5 unlabeled data points (too many overlaps). Consider increasing max.overlaps
# ggplot 코드
p <- ggplot(df, aes(x=row_num, y=Transformed_Log_Na, color=density_cat, shape=Sample)) +
    geom_point() +
    scale_shape_manual(values = c(2, 1)) +
    geom_hline(yintercept=0, linetype="dashed", color = "red") +
    geom_hline(yintercept=c(0.5, -0.5), linetype="dashed", color = "#4682B4") +
    labs(title="Transformed Log  Values by Part with Density", x="Index", y="Transformed_Log_Na") +
    theme_minimal() +
    scale_colour_manual(values = c("Low" = "#2E8B57", "Medium" = "#FF8C00", "High" = "#D2691E", "Very High" = "#DC143C"))

## 라벨 추가하기
p + geom_text_repel(
    data = subset(df, Transformed_Log_Na >= 1 | Transformed_Log_Na <= -1),
    aes(label = name_new, color = NULL, shape = NULL),
    box.padding = 0.5,
    point.padding = 0.5,
    show.legend = FALSE, # 범례 항목 추가 방지
    segment.color = "black",
    min.segment.length = 0,
    max.overlaps = 100, # max.overlaps 값을 조절
    max.iter = 5000 # max.iter 값을 조절
)